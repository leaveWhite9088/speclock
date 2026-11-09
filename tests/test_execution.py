"""执行记录：发布自动产生待办、领取（锁定版本）、报告阻塞 / 失败、提交实现结果（逐条验收条件）、
独立验收（验证者 ≠ 实现者）、新版本取代旧记录、权限与项目隔离。"""

from __future__ import annotations

import json

from speclock import executions
from speclock.db import SessionLocal
from speclock.models import ExecutionRecord
from tests.conftest import (
    ACCEPTANCE_V1,
    change_block,
    commit,
    make_key,
    open_cr,
    publish_v1,
    qa_key,
)

TWO_AC = [
    {"id": "AC-1", **ACCEPTANCE_V1[0]},
    {"name": "日报可查询", "detail": "运营在日报页能查到前一日数据"},
]


def _work(env, headers=None, **params):
    r = env["client"].get("/api/v1/work", params=params, headers=headers or env["agent"])
    assert r.status_code == 200, r.text
    return r.json()


def _one(env, **params):
    rows = _work(env, **params)
    assert len(rows) == 1, rows
    return rows[0]


def _publish_two_ac(env):
    """发布 1.0.0（一条验收条件），再发布 1.1.0（两条）；之后待办是 1.1.0 的记录。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    change_block(env, env["block_id"], acceptance=TWO_AC)


def _results(ids=("AC-1",), result="pass", evidence="自测通过：见测试输出"):
    return [{"ac_id": i, "result": result, "evidence": evidence} for i in ids]


def _post(env, headers, path, body=None):
    return env["client"].post(f"/api/v1/work/{path}", json=body, headers=headers) if body is not None \
        else env["client"].post(f"/api/v1/work/{path}", headers=headers)


def _claim(env, work_id, headers=None):
    r = _post(env, headers or env["agent"], f"{work_id}/claim")
    assert r.status_code == 200, r.text
    return r.json()


def _implement(env, work_id, headers=None, ids=("AC-1",)):
    r = _post(env, headers or env["agent"], f"{work_id}/implementation",
              {"results": _results(ids), "note": "done"})
    assert r.status_code == 200, r.text
    return r.json()


def _verify(env, work_id, headers=None, ids=("AC-1",), result="pass"):
    return _post(env, headers or qa_key(env), f"{work_id}/verification",
                 {"results": _results(ids, result, "独立验证：见截图"), "note": "checked"})


# ---------- 发布产生待办 ----------


def test_publish_creates_a_pending_record(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    assert (w["block_id"], w["version"], w["status"], w["claimed_by"]) == (
        env["block_id"], "1.0.0", "pending", "")
    assert w["block_title"] == "数据采集模块" and w["business"] == "运营"


def test_unpublished_block_has_no_work(env):
    assert _work(env) == []


def test_work_requires_exec_read(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    reviewer = make_key(env, "reviewer")  # 审核人没有 exec.read
    assert env["client"].get("/api/v1/work", headers=reviewer).status_code == 403
    assert env["client"].get("/api/v1/work").status_code == 401


def test_list_filters(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    assert _work(env, status="pending") == [w]
    assert _work(env, status="verified") == []
    assert _work(env, mine=True) == []
    assert _work(env, block_id=env["block_id"]) == [w]
    assert _work(env, capability_id=env["capability_id"]) == [w]
    assert env["client"].get("/api/v1/work", params={"status": "nope"},
                             headers=env["agent"]).status_code == 422
    _claim(env, w["id"])
    assert [x["status"] for x in _work(env, mine=True)] == ["in_progress"]


# ---------- 领取：锁定版本的完整上下文 ----------


def test_claim_returns_pinned_spec_and_marks_in_progress(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    d = _claim(env, w["id"])
    assert d["status"] == "in_progress" and d["claimed_by"]
    spec = d["spec"]
    assert spec["version"] == "1.0.0" and spec["acceptance"][0]["id"] == "AC-1"
    assert spec["rules"] and spec["apis"] and spec["content_md"]
    assert [e["event"] for e in d["events"]] == ["created", "claim"]


def test_cannot_claim_twice(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    other = make_key(env, "executor-agent", label="b")
    r = _post(env, other, f"{w['id']}/claim")
    assert r.status_code == 409 and "已被" in r.json()["detail"]


def test_only_the_holder_can_report(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    other = make_key(env, "executor-agent", label="b")
    for path, body in (
        ("blocked", {"reason": "x"}), ("failed", {"reason": "x"}),
        ("implementation", {"results": _results()}),
    ):
        r = _post(env, other, f"{w['id']}/{path}", body)
        assert r.status_code == 403, (path, r.text)


def test_release_by_holder_or_admin_only(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    other = make_key(env, "executor-agent", label="b")
    assert _post(env, other, f"{w['id']}/release").status_code == 403
    r = _post(env, env["agent"], f"{w['id']}/release")
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["claimed_by"] == ""
    # 管理员（key.manage）可以强制释放
    _claim(env, w["id"], other)
    assert _post(env, env["human"], f"{w['id']}/release").json()["status"] == "pending"
    # pending 状态不能再释放
    assert _post(env, env["agent"], f"{w['id']}/release").status_code == 409


# ---------- 提交实现结果：逐条验收条件 ----------


def test_implementation_needs_every_criterion_with_evidence(env):
    _publish_two_ac(env)
    w = _one(env, status="pending")
    _claim(env, w["id"])
    base = f"{w['id']}/implementation"
    # 缺一条
    r = _post(env, env["agent"], base, {"results": _results(("AC-1",))})
    assert r.status_code == 422 and "AC-2" in json.dumps(r.json(), ensure_ascii=False)
    # 未知条目
    r = _post(env, env["agent"], base, {"results": _results(("AC-1", "AC-9"))})
    assert r.status_code == 422
    # 证据为空
    r = _post(env, env["agent"], base, {"results": [
        {"ac_id": "AC-1", "result": "pass", "evidence": "ok"},
        {"ac_id": "AC-2", "result": "pass", "evidence": "  "}]})
    assert r.status_code == 422 and "evidence" in json.dumps(r.json(), ensure_ascii=False)
    # 重复
    r = _post(env, env["agent"], base, {"results": _results(("AC-1", "AC-1", "AC-2"))})
    assert r.status_code == 422
    # 有一条不通过：不能提交，应该报失败 / 阻塞
    r = _post(env, env["agent"], base, {"results": [
        {"ac_id": "AC-1", "result": "pass", "evidence": "ok"},
        {"ac_id": "AC-2", "result": "fail", "evidence": "查询超时"}]})
    assert r.status_code == 422 and "AC-2" in json.dumps(r.json(), ensure_ascii=False)
    # result 取值非法由 schema 校验
    r = _post(env, env["agent"], base, {"results": [{"ac_id": "AC-1", "result": "maybe", "evidence": "x"}]})
    assert r.status_code == 422
    assert _one(env, status="in_progress")["id"] == w["id"]  # 没有半成品状态变化
    # 全部通过 → implemented
    _implement(env, w["id"], ids=("AC-1", "AC-2"))
    assert _one(env, status="implemented")["id"] == w["id"]


def test_implementation_requires_in_progress(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    r = _post(env, env["agent"], f"{w['id']}/implementation", {"results": _results()})
    assert r.status_code == 409 and "pending" in r.json()["detail"]


# ---------- 独立验收 ----------


def test_full_happy_path_to_verified_with_event_history(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    _implement(env, w["id"])
    r = _verify(env, w["id"])
    assert r.status_code == 200 and r.json()["status"] == "verified"
    d = env["client"].get(f"/api/v1/work/{w['id']}", headers=qa_key(env)).json()
    assert [e["event"] for e in d["events"]] == ["created", "claim", "implemented", "verified"]
    assert d["implementation"][0]["evidence"] and d["verification"][0]["evidence"]
    # verified 是终态
    assert _post(env, env["agent"], f"{w['id']}/claim").status_code == 409


def test_verifier_cannot_be_the_implementer(env):
    """admin 同时有 exec.write 与 exec.verify，但同一把 key 不能自己验收自己。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"], env["human"])
    _implement(env, w["id"], env["human"])
    r = _verify(env, w["id"], env["human"])
    assert r.status_code == 403 and "实现者" in r.json()["detail"]
    assert _verify(env, w["id"]).json()["status"] == "verified"  # 换测试 Agent 就行


def test_permissions_split_executor_and_tester(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    # 执行 Agent 没有验收权限；测试 Agent 没有领取 / 实现权限
    assert _post(env, qa_key(env), f"{w['id']}/claim").status_code == 403
    _claim(env, w["id"])
    _implement(env, w["id"])
    assert _verify(env, w["id"], env["agent"]).status_code == 403
    assert _post(env, qa_key(env), f"{w['id']}/implementation",
                 {"results": _results()}).status_code == 403
    # 但测试 Agent 能读：看到实现方提交的证据
    d = env["client"].get(f"/api/v1/work/{w['id']}", headers=qa_key(env)).json()
    assert d["implementation"] and d["spec"]["acceptance"]


def test_verification_must_cover_every_criterion(env):
    _publish_two_ac(env)
    w = _one(env, status="pending")
    _claim(env, w["id"])
    _implement(env, w["id"], ids=("AC-1", "AC-2"))
    r = _verify(env, w["id"], ids=("AC-1",))
    assert r.status_code == 422
    assert _one(env, status="implemented")["id"] == w["id"]


def test_verification_failure_returns_to_failed_and_can_retry(env):
    _publish_two_ac(env)
    w = _one(env, status="pending")
    _claim(env, w["id"])
    _implement(env, w["id"], ids=("AC-1", "AC-2"))
    r = _post(env, qa_key(env), f"{w['id']}/verification", {"results": [
        {"ac_id": "AC-1", "result": "pass", "evidence": "ok"},
        {"ac_id": "AC-2", "result": "fail", "evidence": "查询返回 500"}]})
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert "AC-2" in r.json()["reason"] and "查询返回 500" in r.json()["reason"]
    # 重新领取（可以是另一个执行 Agent），旧结果被清空，历史保留在事件里
    other = make_key(env, "executor-agent", label="b")
    d = _claim(env, w["id"], other)
    assert d["status"] == "in_progress" and d["implementation"] == []
    assert [e["event"] for e in d["events"]][-3:] == ["implemented", "verify_failed", "claim"]
    _implement(env, w["id"], other, ids=("AC-1", "AC-2"))
    assert _verify(env, w["id"], ids=("AC-1", "AC-2")).json()["status"] == "verified"


# ---------- 阻塞与失败 ----------


def test_blocked_needs_reason_and_can_be_resumed(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    assert _post(env, env["agent"], f"{w['id']}/blocked", {"reason": "  "}).status_code == 422
    r = _post(env, env["agent"], f"{w['id']}/blocked", {"reason": "退款是否含运费？规格没写"})
    assert r.status_code == 200 and r.json()["status"] == "blocked"
    assert _work(env, status="blocked")[0]["reason"].startswith("退款")
    assert _claim(env, w["id"])["status"] == "in_progress"  # 答复后可以重新领取


def test_failed_needs_reason_and_can_be_reclaimed(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    assert _post(env, env["agent"], f"{w['id']}/failed", {"reason": ""}).status_code == 422
    assert _post(env, env["agent"], f"{w['id']}/failed", {"reason": "依赖服务不可用"}).json()["status"] == "failed"
    assert _claim(env, w["id"])["status"] == "in_progress"


# ---------- 新版本取代旧记录 ----------


def test_new_version_supersedes_open_records(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    old = _one(env)
    _claim(env, old["id"])
    change_block(env, env["block_id"], acceptance=TWO_AC)  # 发布 1.x 新版本
    rows = _work(env)
    assert [(r["version"], r["status"]) for r in rows] == [("1.1.0", "pending")] or \
        [r["status"] for r in rows] == ["pending"]
    new = rows[0]
    assert new["id"] != old["id"]
    # 旧记录变 superseded；对它的任何写都 409 并指向最新版本
    d = env["client"].get(f"/api/v1/work/{old['id']}", headers=env["agent"]).json()
    assert d["status"] == "superseded"
    r = _post(env, env["agent"], f"{old['id']}/implementation", {"results": _results()})
    assert r.status_code == 409 and r.json()["detail"]["latest_version"] == new["version"]
    assert _post(env, env["agent"], f"{old['id']}/claim").status_code == 409


def test_verified_records_stay_verified_when_a_new_version_comes(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    _implement(env, w["id"])
    _verify(env, w["id"])
    change_block(env, env["block_id"], acceptance=TWO_AC)
    old = env["client"].get(f"/api/v1/work/{w['id']}", headers=env["agent"]).json()
    assert old["status"] == "verified"
    assert [r["status"] for r in _work(env, status="pending")] == ["pending"]


def test_implemented_but_unverified_record_is_superseded(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    _claim(env, w["id"])
    _implement(env, w["id"])
    change_block(env, env["block_id"], acceptance=TWO_AC)
    assert _verify(env, w["id"]).status_code == 409
    assert env["client"].get(f"/api/v1/work/{w['id']}", headers=env["agent"]).json()["status"] == "superseded"


# ---------- 归档 / 恢复 ----------


def test_archived_block_leaves_the_queue_and_comes_back(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    w = _one(env)
    cr = open_cr(env)
    assert commit(env, cr, [{"op": "archive_block", "id": env["block_id"]}], covers=["AC-1"]).status_code == 200
    assert _work(env) == []
    assert _post(env, env["agent"], f"{w['id']}/claim").status_code == 409
    cr = open_cr(env)
    assert commit(env, cr, [{"op": "restore_block", "id": env["block_id"]}], covers=["AC-1"]).status_code == 200
    assert [x["id"] for x in _work(env)] == [w["id"]]


# ---------- 读侧带上执行状态 ----------


def test_read_sides_show_execution_status(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    w = _one(env)
    _claim(env, w["id"])
    entry = c.get("/api/v1/index", headers=a).json()[0]["capabilities"][0]["blocks"][0]
    assert (entry["work_id"], entry["execution_status"]) == (w["id"], "in_progress")
    blk = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert (blk["work_id"], blk["execution_status"]) == (w["id"], "in_progress")
    manifest = c.get(f"/api/v1/capabilities/{env['capability_id']}", headers=a).json()["manifest"][0]
    assert manifest["execution_status"] == "in_progress"
    tree_block = c.get("/api/v1/tree", headers=h).json()[0]["businesses"][0]["capabilities"][0]["blocks"][0]
    assert tree_block["execution_status"] == "in_progress"
    versions = c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()
    assert versions[0]["execution_status"] == "in_progress"
    assert [e["event"] for e in versions[0]["events"]] == ["created", "claim"]


# ---------- 升级 / 回填 ----------


def test_backfill_creates_missing_records_idempotently(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    db = SessionLocal()
    try:
        db.query(ExecutionRecord).delete()
        db.commit()
        executions.backfill(db)
        executions.backfill(db)
        recs = db.query(ExecutionRecord).all()
        assert [(r.version, r.status) for r in recs] == [("1.0.0", "pending")]
    finally:
        db.close()


def test_old_preset_role_gets_exec_permissions_on_upgrade(env):
    from speclock.models import MigrationMark, Role
    from speclock.permissions import seed_roles

    db = SessionLocal()
    try:
        db.query(MigrationMark).delete()  # 模拟还没做过这次迁移的老库
        role = db.query(Role).filter(Role.name == "executor-agent").one()
        role.permissions_json = json.dumps(["ack.write", "cr.read", "spec.read"])  # 旧版预置
        db.commit()
        seed_roles(db)
        db.refresh(role)
        assert set(json.loads(role.permissions_json)) >= {"exec.read", "exec.write", "cr.read", "spec.read"}
    finally:
        db.close()


# ---------- 创建密钥：Agent 代人创建须附原话 ----------


def test_agent_created_key_needs_human_words_as_evidence(env):
    c, h = env["client"], env["human"]
    body = {"role": "tester-agent", "label": "qa", "via": "natural_language"}
    r = c.post("/api/v1/keys", json=body, headers=h)
    assert r.status_code == 422 and "evidence" in r.json()["detail"]
    r = c.post("/api/v1/keys", json={**body, "evidence": "好，给测试 Agent 建一把"}, headers=h)
    assert r.status_code == 201 and r.json()["role"] == "tester-agent"
    from speclock.models import AuditLog

    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "key_create").order_by(AuditLog.id.desc()).first()
        detail = json.loads(row.detail_json)
        assert detail["via"] == "natural_language" and "测试 Agent" in detail["evidence"]
    finally:
        db.close()
    # 网页 / CLI 直接创建（人自己点的）不需要原话
    assert c.post("/api/v1/keys", json={"role": "scanner-agent", "via": "button"}, headers=h).status_code == 201


def test_mcp_tools_cover_the_execution_protocol_and_ack_is_gone():
    import inspect

    from speclock import mcp_server

    names = {n for n, _ in inspect.getmembers(mcp_server, inspect.isfunction)}
    assert {"list_work", "get_work", "claim_work", "release_work", "report_blocked",
            "report_failed", "submit_implementation", "verify_work", "create_api_key"} <= names
    assert "ack_block" not in names
    assert "evidence" in inspect.signature(mcp_server.create_api_key).parameters
    assert "incomplete_only" not in inspect.signature(mcp_server.get_index).parameters
