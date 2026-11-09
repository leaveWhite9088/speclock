"""联调报告 v2 里确认的问题的回归测试：use_api_key 遇到坏 key 不能毁掉会话、scanner 缺 cr.read 的迁移、
卡在 approved 的内部整理单可以撤回、请求体里不认识的字段直接 422、列出 / 吊销密钥。"""

from __future__ import annotations

import json

import httpx

from speclock.db import SessionLocal
from speclock.models import AuditLog, MigrationMark, Role
from speclock.permissions import seed_roles
from tests.conftest import (
    RULES_V1,
    commit,
    cr_body,
    make_key,
    open_cr,
    publish_v1,
    req_key,
)

CR = "/api/v1/change-requests"


# ---------- use_api_key：坏 key 不能毁掉会话（问题 1） ----------


def _patch_mcp(env, monkeypatch):
    from speclock import mcp_server

    c = env["client"]

    def fake_request(method, url, headers=None, timeout=None, **kw):
        key = (headers or {}).get("X-API-Key", "")
        if key == "agent-boom":  # 模拟请求构造阶段抛出 UnicodeEncodeError
            raise UnicodeEncodeError("ascii", "中", 0, 1, "boom")
        return c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw)

    monkeypatch.setattr(mcp_server.httpx, "request", fake_request)
    admin_key = env["human"]["X-API-Key"]
    monkeypatch.setattr(mcp_server, "CONFIGURED_KEY", admin_key)
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin_key)
    return mcp_server


def test_non_ascii_key_does_not_break_the_session(env, monkeypatch):
    m = _patch_mcp(env, monkeypatch)
    bad = json.loads(m.use_api_key("agent-不存在的key"))
    assert "error" in bad and "保持原来的身份" in bad["error"]
    # 之后的调用照常工作，身份没变
    me = json.loads(m.whoami())
    assert me["status"] == 200 and me["body"]["role"] == "admin"
    assert m.AGENT_KEY == env["human"]["X-API-Key"]


def test_any_error_while_switching_keeps_the_previous_identity(env, monkeypatch):
    m = _patch_mcp(env, monkeypatch)
    bad = json.loads(m.use_api_key("agent-boom"))
    assert "error" in bad
    assert json.loads(m.whoami())["body"]["role"] == "admin"


def test_call_survives_a_non_ascii_key_in_any_tool(env, monkeypatch):
    m = _patch_mcp(env, monkeypatch)
    monkeypatch.setattr(m, "AGENT_KEY", "agent-中文")
    r = json.loads(m.whoami())  # 以前这里会抛异常，整个工具调用报 Error executing tool
    assert r["status"] == 401 and "ASCII" in r["body"]["detail"]


# ---------- scanner 缺 cr.read 的迁移（问题 2） ----------


def test_scanner_role_gets_cr_read_once(env):
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.name == "scanner-agent").one()
        role.permissions_json = json.dumps(["exec.read", "spec.read"])  # 旧库里的样子
        db.query(MigrationMark).filter(MigrationMark.name == "scanner_cr_read").delete()
        db.commit()
        seed_roles(db)
        db.refresh(role)
        assert "cr.read" in json.loads(role.permissions_json)
        # 管理员之后收回，不会被重新补上（一次性迁移）
        role.permissions_json = json.dumps(["exec.read", "spec.read"])
        db.commit()
        seed_roles(db)
        db.refresh(role)
        assert "cr.read" not in json.loads(role.permissions_json)
    finally:
        db.close()


# ---------- 卡在 approved 的内部整理单可以撤回（问题 7） ----------


def _internal(env, submit=True):
    c = env["client"]
    cid = c.post(CR, json=cr_body(kind="internal", kind_reason="只改名"), headers=req_key(env)).json()["id"]
    if submit:
        assert c.post(f"{CR}/{cid}/submit", headers=req_key(env)).status_code == 200
    return cid


def test_stranded_internal_request_can_be_withdrawn_and_redone(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cid = _internal(env)
    # Commit 被「条目总和变了」拦下
    bad = [{"op": "update_block", "id": env["block_id"],
            "rule_ops": [{"op": "upsert", "id": "R-1", "entry": {"name": RULES_V1[0]["name"], "detail": "改了口径"}}]}]
    assert commit(env, cid, bad, covers=["AC-1"]).status_code == 422
    assert c.get(f"{CR}/{cid}", headers=req_key(env)).json()["status"] == "approved"
    # 以前：没有任何办法收场；现在：撤回 → 草稿，批准痕迹清掉
    r = c.post(f"{CR}/{cid}/withdraw", headers=req_key(env))
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert r.json()["decision_via"] == "" and r.json()["decided_by"] == "" and r.json()["content_hash"] == ""
    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "cr_withdraw").order_by(AuditLog.id.desc()).first()
        assert json.loads(row.detail_json) == {"was": "approved_internal_without_commits"}  # 审计里留了记录
    finally:
        db.close()
    # 改成业务变更重新走流程
    assert c.put(f"{CR}/{cid}", json={"kind": "business", "kind_reason": ""}, headers=req_key(env)).status_code == 200
    assert c.post(f"{CR}/{cid}/submit", headers=req_key(env)).json()["status"] == "pending_review"


def test_withdraw_rules_for_approved_requests(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    # 人批准过的业务变更单：不能撤回（批准后不可修改）
    human_approved = open_cr(env)
    r = c.post(f"{CR}/{human_approved}/withdraw", headers=req_key(env))
    assert r.status_code == 409
    # 内部整理单已经有 Commit 落地：不能撤回
    cid = _internal(env)
    ok = [{"op": "update_capability", "id": env["capability_id"], "summary": "新摘要"}]
    assert commit(env, cid, ok, covers=["AC-1"]).status_code == 200
    assert c.post(f"{CR}/{cid}/withdraw", headers=req_key(env)).status_code == 409
    # 别的 key 不能撤回别人的内部整理单
    other_cr = _internal(env)
    other = make_key(env, "requirements-agent", label="别人")
    assert c.post(f"{CR}/{other_cr}/withdraw", headers=other).status_code == 403
    assert c.post(f"{CR}/{other_cr}/withdraw", headers=req_key(env)).json()["status"] == "draft"


# ---------- 请求体里不认识的字段：直接 422（环境问题：旧后端静默丢 kind） ----------


def test_unknown_request_fields_are_rejected(env):
    c, h = env["client"], env["human"]
    r = c.post(CR, json={**cr_body(), "kinds": "internal"}, headers=req_key(env))
    assert r.status_code == 422 and "kinds" in json.dumps(r.json(), ensure_ascii=False)
    cid = c.post(CR, json=cr_body(), headers=req_key(env)).json()["id"]
    assert c.put(f"{CR}/{cid}", json={"titel": "x"}, headers=req_key(env)).status_code == 422
    assert c.post("/api/v1/keys", json={"role": "scanner-agent", "labell": "x"}, headers=h).status_code == 422
    assert c.post(f"{CR}/{cid}/reject", json={"reason": "x", "via": "api", "extra": 1}, headers=h).status_code == 422
    assert c.post(f"{CR}/{cid}/commits", json={"ops": [], "covers": [], "dry_run": True},
                  headers=req_key(env)).status_code == 422  # 正确的字段名是 dryRun
    # 正确的请求照常
    assert c.post(CR, json=cr_body(), headers=req_key(env)).status_code == 201


def test_work_requests_reject_unknown_fields(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    wid = c.get("/api/v1/work", headers=env["agent"]).json()[0]["id"]
    c.post(f"/api/v1/work/{wid}/claim", headers=env["agent"])
    r = c.post(f"/api/v1/work/{wid}/blocked", json={"reason": "x", "reasons": "y"}, headers=env["agent"])
    assert r.status_code == 422


# ---------- 列出 / 吊销密钥（报告「缺什么」） ----------


def test_revoke_key_needs_the_humans_words_when_done_for_them(env):
    c, h = env["client"], env["human"]
    k = c.post("/api/v1/keys", json={"role": "scanner-agent", "label": "旧的"}, headers=h).json()
    r = c.delete(f"/api/v1/keys/{k['id']}", params={"via": "natural_language"}, headers=h)
    assert r.status_code == 422 and "evidence" in r.json()["detail"]
    r = c.delete(f"/api/v1/keys/{k['id']}", params={"via": "natural_language", "evidence": "删掉那把旧的"}, headers=h)
    assert r.status_code == 200
    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "key_delete").order_by(AuditLog.id.desc()).first()
        d = json.loads(row.detail_json)
        assert d["via"] == "natural_language" and d["evidence"] == "删掉那把旧的"
    finally:
        db.close()
    assert c.delete(f"/api/v1/keys/{k['id']}", params={"via": "nope"}, headers=h).status_code == 422
    assert c.delete(f"/api/v1/keys/{k['id']}", headers=h).status_code == 404  # 已经没了


def test_mcp_can_list_and_revoke_keys(env, monkeypatch):
    m = _patch_mcp(env, monkeypatch)
    made = json.loads(m.create_api_key("scanner-agent", "待删", evidence="建一把"))["body"]
    listed = json.loads(m.list_api_keys())["body"]
    row = next(k for k in listed if k["id"] == made["id"])
    assert row["role"] == "scanner-agent" and "key" not in row and "actions_7d" in row
    gone = json.loads(m.revoke_api_key(made["id"], evidence="删掉它"))
    assert gone["status"] == 200 and gone["body"]["deleted"] is True
    assert all(k["id"] != made["id"] for k in json.loads(m.list_api_keys())["body"])
    # 没有 key.manage 的 key 用不了
    scanner = make_key(env, "scanner-agent")
    monkeypatch.setattr(m, "AGENT_KEY", scanner["X-API-Key"])
    assert json.loads(m.list_api_keys())["status"] == 403


def test_httpx_is_the_real_module():
    # 防呆：上面的测试替换的是 mcp_server.httpx.request，确认它真的是 httpx
    from speclock import mcp_server

    assert mcp_server.httpx is httpx
