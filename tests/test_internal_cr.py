"""内部整理审核单：Agent 自行判定、提交即生效；Core 机械检查规则 / 验收条件 / API 的条目总和不变；
move_block；草稿归属（只有开单的 key 或管理员能改）。"""

from __future__ import annotations

import json

from speclock.db import SessionLocal
from speclock.models import AuditLog, BlockVersion, ExecutionRecord
from tests.conftest import (
    ACCEPTANCE_V1,
    APIS_V1,
    RULES_V1,
    commit,
    cr_body,
    make_key,
    open_cr,
    publish_v1,
    req_key,
)

CR = "/api/v1/change-requests"
BG = "# 新模块\n\n这是一段超过二十个字符的业务背景与流程叙述。"
REASON = "只是调整结构，规则、验收条件和 API 一字未改"


def _internal(env, reason=REASON, submit=True, **over):
    c = env["client"]
    r = c.post(CR, json=cr_body(kind="internal", kind_reason=reason, **over), headers=req_key(env))
    assert r.status_code == 201, r.text
    cr_id = r.json()["id"]
    if submit:
        r = c.post(f"{CR}/{cr_id}/submit", headers=req_key(env))
        assert r.status_code == 200, r.text
    return cr_id


def _second_capability(env):
    """用一个业务变更审核单建出第二个小业务，返回它的 id。"""
    cr = open_cr(env)
    r = commit(env, cr, [{"op": "create_capability", "business": env["business_id"],
                          "title": "第二小业务", "ref": "cap2"}], covers=["AC-1"])
    assert r.status_code == 200, r.text
    return r.json()["created"]["$cap2"]["id"]


def _versions(block_id):
    db = SessionLocal()
    try:
        return [v.version for v in db.query(BlockVersion).filter(BlockVersion.block_id == block_id)]
    finally:
        db.close()


# ---------- 提交即生效，留痕 ----------


def test_internal_cr_takes_effect_on_submit_and_records_it(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = _internal(env)
    cr = env["client"].get(f"{CR}/{cr_id}", headers=req_key(env)).json()
    assert cr["kind"] == "internal" and cr["status"] == "approved"
    assert cr["decision_via"] == "agent_declared" and cr["decision_evidence"] == REASON
    assert cr["decided_by"] == cr["created_by"]
    db = SessionLocal()
    try:
        row = (db.query(AuditLog).filter(AuditLog.action == "cr_approve", AuditLog.target == f"cr:{cr_id}").one())
        detail = json.loads(row.detail_json)
        assert detail["via"] == "agent_declared" and detail["kind"] == "internal"
    finally:
        db.close()


def test_business_cr_is_still_the_default_and_needs_a_human(env):
    cr = env["client"].post(CR, json=cr_body(), headers=req_key(env)).json()
    assert cr["kind"] == "business"
    env["client"].post(f"{CR}/{cr['id']}/submit", headers=req_key(env))
    assert env["client"].get(f"{CR}/{cr['id']}", headers=req_key(env)).json()["status"] == "pending_review"


def test_internal_needs_a_reason_and_the_permission(env):
    c = env["client"]
    cr_id = _internal(env, reason="", submit=False)
    r = c.post(f"{CR}/{cr_id}/submit", headers=req_key(env))
    assert r.status_code == 422 and "kind_reason" in json.dumps(r.json(), ensure_ascii=False)
    # 没有 cr.internal 的角色开不了
    rid = next(x["id"] for x in c.get("/api/v1/roles", headers=env["human"]).json()
               if x["name"] == "requirements-agent")
    perms = [p for p in c.get("/api/v1/roles", headers=env["human"]).json()
             if p["name"] == "requirements-agent"][0]["permissions"]
    c.put(f"/api/v1/roles/{rid}", headers=env["human"],
          json={"permissions": [p for p in perms if p != "cr.internal"]})
    r = c.post(CR, json=cr_body(kind="internal", kind_reason=REASON), headers=req_key(env))
    assert r.status_code == 403 and "cr.internal" in r.json()["detail"]
    # 改成业务变更则不受影响
    assert c.post(CR, json=cr_body(), headers=req_key(env)).status_code == 201


def test_internal_cannot_supersede(env):
    cr_id = _internal(env, submit=False)
    old = open_cr(env)
    r = env["client"].put(f"{CR}/{cr_id}", json={"supersedes_id": old}, headers=req_key(env))
    assert r.status_code == 200
    r = env["client"].post(f"{CR}/{cr_id}/submit", headers=req_key(env))
    assert r.status_code == 422 and "取代" in r.json()["detail"]


# ---------- 机械兜底：条目总和不变 ----------


def test_renames_and_summaries_pass_without_new_versions(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = _internal(env)
    ops = [
        {"op": "update_business", "id": env["business_id"], "name": "运营中心"},
        {"op": "update_capability", "id": env["capability_id"], "title": "经营日报（新）", "summary": "新摘要"},
        {"op": "update_block", "id": env["block_id"], "title": "数据采集（新）"},
    ]
    r = commit(env, cr_id, ops, covers=["AC-1"])
    assert r.status_code == 200, r.text
    assert _versions(env["block_id"]) == ["1.0.0"]  # 标题不进版本快照，不产生新的模块版本


def test_changing_a_rule_is_rejected_and_rolled_back(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = _internal(env)
    ops = [{"op": "update_block", "id": env["block_id"],
            "rule_ops": [{"op": "upsert", "id": "R-1",
                          "entry": {"name": RULES_V1[0]["name"], "detail": "悄悄改了口径"}}]}]
    r = commit(env, cr_id, ops, covers=["AC-1"])
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "业务内容" in detail["error"] and detail["added_or_changed"] and detail["removed_or_changed"]
    assert _versions(env["block_id"]) == ["1.0.0"]  # 整个 Commit 回滚
    # 同样的改动走业务变更审核单是允许的
    assert commit(env, open_cr(env), ops, covers=["AC-1"]).status_code == 200


def test_adding_removing_or_restoring_content_is_rejected(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    # 新建一个有新内容的模块
    new = {"op": "create_block", "capability": env["capability_id"], "title": "新增", "content_md": BG,
           "rules": [{"name": "全新规则", "detail": "之前没有"}], "apis": [], "acceptance": ACCEPTANCE_V1}
    r = commit(env, _internal(env), [new], covers=["AC-1"])
    assert r.status_code == 422 and "业务内容" in r.json()["detail"]["error"]
    # 只归档（知识消失）
    r = commit(env, _internal(env), [{"op": "archive_block", "id": env["block_id"]}], covers=["AC-1"])
    assert r.status_code == 422
    # 业务变更归档后，内部整理不能把它恢复回来（相当于新增内容）
    assert commit(env, open_cr(env), [{"op": "archive_block", "id": env["block_id"]}],
                  covers=["AC-1"]).status_code == 200
    r = commit(env, _internal(env), [{"op": "restore_block", "id": env["block_id"]}], covers=["AC-1"])
    assert r.status_code == 422


def test_merging_modules_keeps_the_totals_and_is_allowed(env):
    """新建一个带完全相同条目的模块、同时归档旧的：条目总和没变，属于重组。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    ops = [
        {"op": "create_block", "capability": env["capability_id"], "title": "合并后的采集模块",
         "content_md": BG, "rules": RULES_V1, "apis": APIS_V1, "acceptance": ACCEPTANCE_V1},
        {"op": "archive_block", "id": env["block_id"]},
    ]
    r = commit(env, _internal(env), ops, covers=["AC-1"])
    assert r.status_code == 200, r.text
    assert len(r.json()["blocks"]) == 1 and r.json()["archived_blocks"] == [env["block_id"]]


# ---------- move_block ----------


def test_move_block_keeps_identity_history_and_work_records(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cap2 = _second_capability(env)
    db = SessionLocal()
    try:
        works_before = db.query(ExecutionRecord).count()
    finally:
        db.close()
    r = commit(env, _internal(env), [{"op": "move_block", "id": env["block_id"], "capability": cap2}],
               covers=["AC-1"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["moved_blocks"] == [env["block_id"]]
    assert {v["capability_id"] for v in out["capability_versions"]} == {env["capability_id"], cap2}
    assert _versions(env["block_id"]) == ["1.0.0"]  # 模块自己没有新版本
    db = SessionLocal()
    try:
        assert db.query(ExecutionRecord).count() == works_before  # 执行记录不受影响
    finally:
        db.close()
    # 新小业务的 manifest 里有它，原小业务里没有了
    new_cap = c.get(f"/api/v1/capabilities/{cap2}", headers=env["agent"]).json()
    old_cap = c.get(f"/api/v1/capabilities/{env['capability_id']}", headers=env["agent"]).json()
    assert [m["block_id"] for m in new_cap["manifest"]] == [env["block_id"]]
    assert env["block_id"] not in [m["block_id"] for m in old_cap["manifest"]]
    index = c.get("/api/v1/index", headers=env["agent"]).json()
    placed = {cap["capability_id"]: [b["block_id"] for b in cap["blocks"]]
              for biz in index for cap in biz["capabilities"]}
    assert placed[cap2] == [env["block_id"]]


def test_move_block_validations(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cap2 = _second_capability(env)
    bid = env["block_id"]
    # 已经在那里
    r = commit(env, open_cr(env), [{"op": "move_block", "id": bid, "capability": env["capability_id"]}],
               covers=["AC-1"])
    assert r.status_code == 422 and "无需搬动" in r.json()["detail"]
    # 不存在的小业务
    r = commit(env, open_cr(env), [{"op": "move_block", "id": bid, "capability": 9999}], covers=["AC-1"])
    assert r.status_code == 404
    # 业务变更审核单同样可以搬（不要求内部整理）
    r = commit(env, open_cr(env), [{"op": "move_block", "id": bid, "capability": cap2}], covers=["AC-1"])
    assert r.status_code == 200


# ---------- 草稿归属 ----------


def test_only_the_creator_or_an_admin_can_touch_a_draft(env):
    c = env["client"]
    draft = c.post(CR, json=cr_body(), headers=req_key(env)).json()["id"]
    other = make_key(env, "requirements-agent", label="另一个需求 Agent")
    for method, path, body in (
        ("PUT", f"{CR}/{draft}", {"title": "被改了"}),
        ("POST", f"{CR}/{draft}/submit", None),
    ):
        r = c.request(method, path, headers=other, **({"json": body} if body else {}))
        assert r.status_code == 403 and "只有它" in r.json()["detail"], (method, r.text)
    # 开单的 key 可以；管理员也可以
    assert c.put(f"{CR}/{draft}", json={"title": "自己改"}, headers=req_key(env)).status_code == 200
    assert c.put(f"{CR}/{draft}", json={"title": "管理员改"}, headers=env["human"]).status_code == 200
    assert c.post(f"{CR}/{draft}/submit", headers=req_key(env)).status_code == 200
    # 撤回同样只有开单的 key 或管理员
    assert c.post(f"{CR}/{draft}/withdraw", headers=other).status_code == 403
    assert c.post(f"{CR}/{draft}/withdraw", headers=req_key(env)).status_code == 200


# ---------- 预置角色 ----------


def test_scanner_can_read_but_cannot_open_requests_or_write(env):
    c = env["client"]
    scanner = make_key(env, "scanner-agent")
    me = c.get("/api/v1/me", headers=scanner).json()
    assert me["permissions"] == ["cr.read", "exec.read", "spec.read"]
    assert c.get("/api/v1/index", headers=scanner).status_code == 200
    assert c.get(CR, headers=scanner).status_code == 200
    assert c.post(CR, json=cr_body(), headers=scanner).status_code == 403
    assert c.post(CR, json=cr_body(kind="internal", kind_reason="x"), headers=scanner).status_code == 403
    assert c.post(f"{CR}/1/commits", json={"ops": [{"op": "archive_block", "id": 1}]},
                  headers=scanner).status_code == 403


def test_cr_internal_permission_is_on_requirements_and_admin_by_default(env):
    roles = {r["name"]: r["permissions"] for r in env["client"].get("/api/v1/roles", headers=env["human"]).json()}
    assert "cr.internal" in roles["requirements-agent"] and "cr.internal" in roles["admin"]
    assert "cr.internal" not in roles["executor-agent"] and "cr.internal" not in roles["scanner-agent"]
