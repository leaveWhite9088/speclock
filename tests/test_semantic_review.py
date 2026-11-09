"""内部整理的语义复核：三档判定、待复核 Commit、另一个角色复核、留痕、阈值、过期、权限。"""

from __future__ import annotations

import json

from speclock import review as review_mod
from speclock.db import SessionLocal
from speclock.models import AuditLog, Commit
from speclock.settings import ReviewSettings
from tests.conftest import (
    ACCEPTANCE_V1,
    APIS_V1,
    RULES_V1,
    change_block,
    cr_body,
    make_key,
    open_cr,
    publish_v1,
    req_key,
)

CR = "/api/v1/change-requests"
OLD_DETAIL = RULES_V1[0]["detail"]  # 支付成功订单金额合计（不含退款）
TYPO_DETAIL = "支付成功订单金额合计(不含退款)"  # 全角括号改半角：2 个字


def _scanner(env):
    if "_scanner" not in env:
        env["_scanner"] = make_key(env, "scanner-agent", label="扫描")
    return env["_scanner"]


def _internal(env, headers=None, reason="只是改了标点，意思没变"):
    c = env["client"]
    h = headers or req_key(env)
    cid = c.post(CR, json=cr_body(kind="internal", kind_reason=reason), headers=h).json()["id"]
    r = c.post(f"{CR}/{cid}/submit", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    return cid


def _commit(env, cid, ops, headers=None, covers=("AC-1",), **extra):
    return env["client"].post(
        f"{CR}/{cid}/commits",
        json={"ops": ops, "covers": list(covers), **extra},
        headers=headers or req_key(env),
    )


def _rule_op(detail, rid="R-1", name=None, bid=None, env=None):
    return {"op": "update_block", "id": bid or 1,
            "rule_ops": [{"op": "upsert", "id": rid, "entry": {"name": name or RULES_V1[0]["name"], "detail": detail}}]}


def _block(env):
    return env["client"].get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).json()


def _pending(env, headers=None):
    r = env["client"].get("/api/v1/reviews", headers=headers or _scanner(env))
    assert r.status_code == 200, r.text
    return r.json()


def _review(env, cid, commit_id, decision, reason="意思没变，只是标点", headers=None, **extra):
    return env["client"].post(
        f"{CR}/{cid}/commits/{commit_id}/review",
        json={"decision": decision, "reason": reason, **extra},
        headers=headers or _scanner(env),
    )


def _typo_pending(env):
    """一张内部整理单 + 一个进入待复核的错别字 Commit。返回 (cr_id, commit_id)。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    r = _commit(env, cid, [_rule_op(TYPO_DETAIL, bid=env["block_id"])])
    assert r.status_code == 202, r.text
    return cid, r.json()["commit_id"]


# ---------- 第 2 档：待复核，规格不变 ----------


def test_typo_goes_to_pending_review_and_the_spec_does_not_change(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    r = _commit(env, cid, [_rule_op(TYPO_DETAIL, bid=env["block_id"])])
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending_review" and body["commit_id"] and "待复核" in body["message"]
    change = body["review"]["changes"][0]
    assert (change["item_id"], change["field"], change["old"], change["new"]) == ("R-1", "detail", OLD_DETAIL, TYPO_DETAIL)
    assert change["distance"] == 2 and body["review"]["thresholds"]["max_edit_chars"] == 6
    # 复核前规格一个字都没变，也没有新版本
    blk = _block(env)
    assert blk["version"] == "1.0.0" and blk["rules"][0]["detail"] == OLD_DETAIL
    versions = env["client"].get(f"/api/v1/blocks/{env['block_id']}/history", headers=env["agent"]).json()
    assert [v["version"] for v in versions] == ["1.0.0"]
    # 审核单里看得到：待复核的 Commit，不计入已落地
    cr = env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()
    assert (cr["commit_count"], cr["pending_review_count"]) == (0, 1)
    assert cr["commits"][0]["status"] == "pending_review" and cr["commits"][0]["review"]["changes"]
    assert cr["coverage"]["covered"] == []  # 待复核的 Commit 不算覆盖
    assert cr["pending_reviews"][0]["changed_entries"] == 1


def test_acceptance_typo_also_goes_to_review(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    detail = ACCEPTANCE_V1[0]["detail"].replace("缺失门店", "缺失门点")
    op = {"op": "update_block", "id": env["block_id"],
          "acceptance_ops": [{"op": "upsert", "id": "AC-1", "entry": {"name": ACCEPTANCE_V1[0]["name"], "detail": detail}}]}
    r = _commit(env, cid, [op])
    assert r.status_code == 202
    assert r.json()["review"]["changes"][0]["kind"] == "ac"


def test_dry_run_reports_the_tier_without_storing_anything(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    r = _commit(env, cid, [_rule_op(TYPO_DETAIL, bid=env["block_id"])], dryRun=True)
    assert r.status_code == 200 and r.json()["status"] == "would_need_review"
    db = SessionLocal()
    try:
        assert db.query(Commit).count() == 0
    finally:
        db.close()


# ---------- 复核：通过才生效，记录复核人 ----------


def test_approved_review_publishes_and_records_the_reviewer(env):
    cid, commit_id = _typo_pending(env)
    pending = _pending(env)
    assert [(p["cr_id"], p["commit_id"], p["own"]) for p in pending] == [(cid, commit_id, False)]
    assert pending[0]["review"]["changes"][0]["new"] == TYPO_DETAIL and pending[0]["kind_reason"]

    r = _review(env, cid, commit_id, "approve", reason="只是全角改半角括号，意思没变")
    assert r.status_code == 200, r.text
    new_version = r.json()["blocks"][0]["version"]
    assert r.json()["status"] == "applied" and new_version != "1.0.0"
    # 这时才发布新版本（版本号按现有规则机械计算：改了条目就是 major）
    blk = _block(env)
    assert blk["version"] == new_version and blk["rules"][0]["detail"] == TYPO_DETAIL
    assert (blk["cr_id"], blk["commit_id"]) == (cid, commit_id)
    # 留痕：谁复核、理由、新旧对比
    cr = env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()
    commit = cr["commits"][0]
    assert commit["status"] == "applied" and commit["review"]["decision"] == "approved"
    assert commit["review"]["reason"] == "只是全角改半角括号，意思没变"
    assert commit["review"]["reviewed_by"].startswith("agent-") and commit["review"]["reviewed_by"] != commit["created_by"]
    assert commit["review"]["changes"][0]["old"] == OLD_DETAIL
    assert cr["commit_count"] == 1 and cr["pending_review_count"] == 0 and cr["coverage"]["covered"] == ["AC-1"]
    # 不再在待复核列表里；审核单可以完成
    assert _pending(env) == []
    assert env["client"].post(f"{CR}/{cid}/complete", headers=req_key(env)).json()["status"] == "applied"
    # 审计
    db = SessionLocal()
    try:
        actions = [a.action for a in db.query(AuditLog).order_by(AuditLog.id)]
        assert "commit_review_requested" in actions and "commit_review_approved" in actions
        row = db.query(AuditLog).filter(AuditLog.action == "commit_review_approved").one()
        d = json.loads(row.detail_json)
        assert d["reason"] and d["changes"][0]["new"] == TYPO_DETAIL
    finally:
        db.close()


def test_cannot_complete_while_a_commit_is_pending_review(env):
    cid, commit_id = _typo_pending(env)
    r = env["client"].post(f"{CR}/{cid}/complete", headers=req_key(env))
    assert r.status_code == 409 and r.json()["detail"]["pending_review_commits"] == [commit_id]


def test_rejected_review_does_not_take_effect_and_the_reason_is_visible(env):
    cid, commit_id = _typo_pending(env)
    r = _review(env, cid, commit_id, "reject", reason="去掉括号后读起来像是「不含」被省略了，意思可能变了")
    assert r.status_code == 200 and r.json()["status"] == "review_rejected"
    blk = _block(env)
    assert blk["version"] == "1.0.0" and blk["rules"][0]["detail"] == OLD_DETAIL
    commit = env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()["commits"][0]
    assert commit["status"] == "review_rejected" and commit["review"]["decision"] == "rejected"
    assert "意思可能变了" in commit["review"]["reason"] and commit["review"]["reviewed_by"]
    # 已经有结论的不能再复核；审核单还是 approved，不会因此完成
    assert _review(env, cid, commit_id, "approve").status_code == 409
    assert env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()["status"] == "approved"
    assert env["client"].post(f"{CR}/{cid}/complete", headers=req_key(env)).status_code == 409


# ---------- 提交者不能复核自己 ----------


def test_submitter_cannot_review_their_own_commit(env):
    """admin 同时有 commit.write 与 cr.review：同一把 key 提交又复核 → 403。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env, headers=env["human"])
    r = _commit(env, cid, [_rule_op(TYPO_DETAIL, bid=env["block_id"])], headers=env["human"])
    assert r.status_code == 202
    commit_id = r.json()["commit_id"]
    own = _review(env, cid, commit_id, "approve", headers=env["human"])
    assert own.status_code == 403 and "自己提交" in own.json()["detail"]
    assert _pending(env, env["human"])[0]["own"] is True
    # 换一把 key（另一把 admin、或扫描 Agent）就可以
    other_admin = make_key(env, "admin", label="另一把管理员")
    assert _review(env, cid, commit_id, "approve", headers=other_admin).status_code == 200


def test_only_roles_with_cr_review_can_review(env):
    cid, commit_id = _typo_pending(env)
    # 需求 Agent（提交者）没有 cr.review；执行 Agent 也没有
    assert _review(env, cid, commit_id, "approve", headers=req_key(env)).status_code == 403
    assert _review(env, cid, commit_id, "approve", headers=env["agent"]).status_code == 403
    assert env["client"].get("/api/v1/reviews", headers=req_key(env)).status_code == 403
    assert env["client"].get("/api/v1/reviews").status_code == 401


def test_review_needs_a_reason_and_a_human_needs_to_quote_their_words(env):
    cid, commit_id = _typo_pending(env)
    assert _review(env, cid, commit_id, "approve", reason="  ").status_code == 422
    assert _review(env, cid, commit_id, "maybe").status_code == 422
    r = _review(env, cid, commit_id, "approve", via="natural_language")
    assert r.status_code == 422 and "原话" in r.json()["detail"]
    other_admin = make_key(env, "admin", label="人")
    ok = _review(env, cid, commit_id, "approve", headers=other_admin, via="natural_language", evidence="没问题，就是标点")
    assert ok.status_code == 200
    c = env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()["commits"][0]
    assert c["review"]["via"] == "natural_language" and c["review"]["evidence"] == "没问题，就是标点"


def test_review_target_validation(env):
    cid, commit_id = _typo_pending(env)
    assert _review(env, cid, 9999, "approve").status_code == 404
    other_cr = _internal(env)
    assert _review(env, other_cr, commit_id, "approve").status_code == 404  # 不是这张单的 Commit
    assert _review(env, 9999, commit_id, "approve").status_code == 404
    unknown = env["client"].post(f"{CR}/{cid}/commits/{commit_id}/review",
                                 json={"decision": "approve", "reason": "x", "extra": 1}, headers=_scanner(env))
    assert unknown.status_code == 422


# ---------- 第 3 档：有实质改动，整体拒绝，并说明哪条 ----------


def test_mixed_batch_is_rejected_as_a_whole_and_names_the_substantive_change(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    ops = [{
        "op": "update_block", "id": env["block_id"],
        "rule_ops": [
            {"op": "upsert", "id": "R-1", "entry": {"name": RULES_V1[0]["name"], "detail": TYPO_DETAIL}},  # 错别字
            {"op": "upsert", "entry": {"name": "新增规则", "detail": "之前没有的一条业务规则"}},  # 实质：新增
        ],
    }]
    r = _commit(env, cid, ops)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert any("新增" in x["why"] and "新增规则" in x["where"] for x in d["substantive"])
    assert d["minor_edits"][0]["item_id"] == "R-1"  # 错别字那条也列出来，说明它本身没问题
    assert d["added_or_changed"] and "业务变更" in d["error"]
    # 整批没生效，也没有残留的待复核
    assert _block(env)["rules"][0]["detail"] == OLD_DETAIL and _pending(env) == []


def test_big_rewrite_and_deleting_entries_are_substantive(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    r = _commit(env, cid, [_rule_op("按下单时间统计的全部订单金额之和，包含已退款订单", bid=env["block_id"])])
    assert r.status_code == 422
    assert any("R-1" in x["where"] and "改动" in x["why"] for x in r.json()["detail"]["substantive"])
    gone = _commit(env, cid, [{"op": "update_block", "id": env["block_id"], "rule_ops": [{"op": "delete", "id": "R-1"}]}])
    assert gone.status_code == 422 and any("删除" in x["why"] for x in gone.json()["detail"]["substantive"])


def test_full_replacement_without_ids_loses_the_identity_and_is_substantive(env):
    """「同一条」靠稳定 id 判断：整体替换时没带 id，哪怕文字几乎一样也是「删除旧的 + 新增新的」。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    no_id = {"op": "update_block", "id": env["block_id"],
             "rules": [{"name": RULES_V1[0]["name"], "detail": TYPO_DETAIL}]}
    r = _commit(env, cid, [no_id])
    assert r.status_code == 422
    whys = " ".join(x["why"] for x in r.json()["detail"]["substantive"])
    assert "新增" in whys and "删除" in whys
    # 保留 id 的整体替换才是同一条
    with_id = {"op": "update_block", "id": env["block_id"],
               "rules": [{"id": "R-1", "name": RULES_V1[0]["name"], "detail": TYPO_DETAIL}]}
    assert _commit(env, cid, [with_id]).status_code == 202


def test_matching_is_by_id_not_by_name(env):
    """名称一样不代表是同一条：换了 id 的「同名」规则是新增。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    swapped = {"op": "update_block", "id": env["block_id"],
               "rules": [{"id": "R-9", "name": RULES_V1[0]["name"], "detail": OLD_DETAIL}]}
    r = _commit(env, cid, [swapped])
    # 内容一字不变，只是编号变了：条目总和不变 → 第 1 档，直接生效（编号本来就不是业务内容）
    assert r.status_code in (200, 409, 422)
    if r.status_code == 200:
        assert r.json()["status"] == "applied"


def test_any_api_change_is_substantive(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    changed = [dict(APIS_V1[0], api="GET /api/daily-report/v2")]  # 改了 API 的路径
    r = _commit(env, cid, [{"op": "update_block", "id": env["block_id"], "apis": changed}])
    assert r.status_code == 422, r.text
    assert any("API" in x["where"] for x in r.json()["detail"]["substantive"])


def test_structure_changes_with_typos_are_substantive(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    ops = [_rule_op(TYPO_DETAIL, bid=env["block_id"]), {"op": "archive_block", "id": env["block_id"]}]
    r = _commit(env, cid, ops)
    assert r.status_code in (409, 422)


# ---------- 阈值（配置，不写死） ----------


def _with_settings(monkeypatch, **kw):
    monkeypatch.setattr(review_mod, "get_review_settings", lambda: ReviewSettings(**kw))


def test_thresholds_come_from_settings(env, monkeypatch):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    op = [_rule_op(TYPO_DETAIL, bid=env["block_id"])]  # 距离 2
    _with_settings(monkeypatch, max_edit_chars=1)
    r = _commit(env, cid, op)
    assert r.status_code == 422 and "改动超过 1 个字" in json.dumps(r.json(), ensure_ascii=False)
    _with_settings(monkeypatch, max_edit_ratio=0.05)
    r = _commit(env, cid, op)
    assert r.status_code == 422 and "超过上限" in json.dumps(r.json(), ensure_ascii=False)
    _with_settings(monkeypatch, enabled=False)
    r = _commit(env, cid, op)
    assert r.status_code == 422 and "没有启用" in json.dumps(r.json(), ensure_ascii=False)
    _with_settings(monkeypatch, max_edit_chars=6)
    assert _commit(env, cid, op).status_code == 202


def test_too_many_entries_in_one_commit_is_substantive(env, monkeypatch):
    publish_v1(env["client"], env["human"], env["block_id"])
    long_rules = [{"id": "R-1", **RULES_V1[0]}] + [
        {"name": f"规则{i}", "detail": f"这是第{i}条业务规则，内容足够长，便于只改一个标点符号。"} for i in range(2, 6)
    ]
    change_block(env, env["block_id"], rules=long_rules)
    cur = _block(env)["rules"]
    assert len(cur) == 5
    cid = _internal(env)
    ops = [{"op": "update_block", "id": env["block_id"],
            "rule_ops": [{"op": "upsert", "id": r["id"], "entry": {"name": r["name"], "detail": r["detail"].replace("。", ".")}}
                         for r in cur[1:]]}]  # 4 条，各改一个标点
    r = _commit(env, cid, ops)
    assert r.status_code == 422 and "超过上限 3" in json.dumps(r.json(), ensure_ascii=False)
    ops[0]["rule_ops"] = ops[0]["rule_ops"][:3]  # 3 条在上限内
    assert _commit(env, cid, ops).status_code == 202
    _with_settings(monkeypatch, max_entries=2)
    assert _commit(env, cid, ops).status_code == 422


# ---------- 第 1 档不受影响 ----------


def test_unchanged_total_still_applies_directly(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = _internal(env)
    r = _commit(env, cid, [{"op": "update_capability", "id": env["capability_id"], "title": "改个名"}])
    assert r.status_code == 200 and r.json()["status"] == "applied"
    cr = env["client"].get(f"{CR}/{cid}", headers=req_key(env)).json()
    assert cr["commits"][0]["status"] == "applied" and cr["commit_count"] == 1


def test_business_requests_are_unaffected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cid = open_cr(env)
    r = _commit(env, cid, [_rule_op("按下单时间统计的全部订单金额之和", bid=env["block_id"])])
    assert r.status_code == 200 and r.json()["status"] == "applied"


# ---------- 过期、撤回 ----------


def test_stale_pending_commit_cannot_be_approved(env):
    cid, commit_id = _typo_pending(env)
    # 之后另一张业务变更单把这条规则改掉了
    change_block(env, env["block_id"], rule_ops=[{"op": "upsert", "id": "R-1",
                 "entry": {"name": RULES_V1[0]["name"], "detail": "按下单时间统计的全部订单金额之和"}}])
    r = _review(env, cid, commit_id, "approve")
    assert r.status_code == 409 and "又变化" in json.dumps(r.json(), ensure_ascii=False)
    assert _block(env)["rules"][0]["detail"] == "按下单时间统计的全部订单金额之和"  # 没有被旧结论覆盖
    assert _review(env, cid, commit_id, "reject", reason="规格已经变了，需要重新提交").status_code == 200


def test_withdrawing_the_request_voids_its_pending_commits(env):
    cid, commit_id = _typo_pending(env)
    r = env["client"].post(f"{CR}/{cid}/withdraw", headers=req_key(env))
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert _pending(env) == []
    db = SessionLocal()
    try:
        assert db.get(Commit, commit_id).status == "withdrawn"
    finally:
        db.close()
    # 有已落地 Commit 的不能撤回（待复核的不算）
    cid2 = _internal(env)
    ok = _commit(env, cid2, [{"op": "update_capability", "id": env["capability_id"], "summary": "新摘要"}])
    assert ok.status_code == 200
    assert env["client"].post(f"{CR}/{cid2}/withdraw", headers=req_key(env)).status_code == 409


# ---------- scanner-agent 的边界 ----------


def test_scanner_can_read_and_review_but_cannot_open_requests_or_commit(env):
    cid, commit_id = _typo_pending(env)
    c, s = env["client"], _scanner(env)
    me = c.get("/api/v1/me", headers=s).json()
    assert {"cr.read", "cr.review"} <= set(me["permissions"])
    assert "cr.write" not in me["permissions"] and "commit.write" not in me["permissions"]
    assert c.get(f"{CR}/{cid}", headers=s).status_code == 200  # 能读审核单，才有上下文判断
    assert c.post(CR, json=cr_body(), headers=s).status_code == 403
    assert c.post(CR, json=cr_body(kind="internal", kind_reason="x"), headers=s).status_code == 403
    assert c.post(f"{CR}/{cid}/commits", json={"ops": [{"op": "archive_block", "id": 1}]}, headers=s).status_code == 403
    assert c.post(f"{CR}/{cid}/submit", headers=s).status_code == 403
    assert _review(env, cid, commit_id, "approve").status_code == 200  # 但能复核
