"""联调报告里确认存在的问题的回归测试：reason 残留、409 缺新记录 id、空库 401 无提示、
校验分阶段遮住缺失项、$ref 写法报错不友好。"""

from __future__ import annotations

import json

from speclock.db import SessionLocal
from speclock.models import ApiKey
from tests.conftest import (
    ACCEPTANCE_V1,
    APIS_NO_DESC,
    change_block,
    commit,
    open_cr,
    publish_v1,
    qa_key,
)

BG = "# 新模块\n\n这是一段超过二十个字符的业务背景与流程叙述。"
TWO_AC = [{"id": "AC-1", **ACCEPTANCE_V1[0]}, {"name": "第二条", "detail": "另一条验收"}]


def _work(env, **params):
    return env["client"].get("/api/v1/work", params=params, headers=env["agent"]).json()


def _results(ids, result="pass", evidence="ok"):
    return [{"ac_id": i, "result": result, "evidence": evidence} for i in ids]


# ---------- reason 不再残留 ----------


def test_reason_is_cleared_when_a_failed_task_is_reclaimed(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    wid = _work(env)[0]["id"]
    c.post(f"/api/v1/work/{wid}/claim", headers=env["agent"])
    c.post(f"/api/v1/work/{wid}/implementation",
           json={"results": _results(["AC-1"])}, headers=env["agent"])
    r = c.post(f"/api/v1/work/{wid}/verification",
               json={"results": _results(["AC-1"], "fail", "证据不足")}, headers=qa_key(env))
    assert r.json()["status"] == "failed" and "证据不足" in r.json()["reason"]
    claimed = c.post(f"/api/v1/work/{wid}/claim", headers=env["agent"]).json()
    assert claimed["status"] == "in_progress" and claimed["reason"] == ""
    # 历史仍在事件里
    assert any("证据不足" in e["note"] for e in claimed["events"])
    c.post(f"/api/v1/work/{wid}/implementation",
           json={"results": _results(["AC-1"])}, headers=env["agent"])
    done = c.post(f"/api/v1/work/{wid}/verification",
                  json={"results": _results(["AC-1"])}, headers=qa_key(env)).json()
    assert done["status"] == "verified" and done["reason"] == ""


# ---------- 409 带上新记录的 id ----------


def test_superseded_409_points_to_the_new_work_id(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    old = _work(env)[0]
    c.post(f"/api/v1/work/{old['id']}/claim", headers=env["agent"])
    change_block(env, env["block_id"], acceptance=TWO_AC)
    new = _work(env, status="pending")[0]
    r = c.post(f"/api/v1/work/{old['id']}/implementation",
               json={"results": _results(["AC-1"])}, headers=env["agent"])
    detail = r.json()["detail"]
    assert r.status_code == 409
    assert (detail["latest_version"], detail["latest_work_id"]) == (new["version"], new["id"])


# ---------- 空库的 401 有提示 ----------


def test_unknown_key_on_an_empty_key_table_explains_how_to_recover(env):
    db = SessionLocal()
    try:
        db.query(ApiKey).delete()
        db.commit()
    finally:
        db.close()
    r = env["client"].get("/api/v1/me", headers={"X-API-Key": "human-whatever"})
    assert r.status_code == 401 and "seed --empty" in r.json()["detail"]


def test_unknown_key_with_other_keys_present_stays_terse(env):
    r = env["client"].get("/api/v1/me", headers={"X-API-Key": "human-whatever"})
    assert r.status_code == 401 and r.json()["detail"] == "unknown API key"


# ---------- 一次列全缺失项 ----------


def test_create_block_lists_api_desc_together_with_other_missing_items(env):
    cr = open_cr(env)
    op = {"op": "create_block", "capability": env["capability_id"], "title": "半成品",
          "content_md": "短", "rules": [], "apis": APIS_NO_DESC, "acceptance": []}
    r = commit(env, cr, [op], covers=["AC-1"])
    assert r.status_code == 422, r.text
    missing = json.dumps(r.json()["detail"], ensure_ascii=False)
    for needle in ("20 个字符", "规则", "验收条件", "desc"):
        assert needle in missing, (needle, missing)


# ---------- $ref 写法的报错 ----------


def test_ref_errors_explain_the_dollar_prefix_convention(env):
    cr = open_cr(env)
    ops = [
        {"op": "create_business", "name": "运营", "ref": "biz"},
        {"op": "create_capability", "business": {"$ref": "biz"}, "title": "日报"},
    ]
    r = commit(env, cr, ops, covers=["AC-1"])
    assert r.status_code == 422 and "$biz" in r.json()["detail"]
    ops[1]["business"] = "biz"  # 漏了 $ 前缀
    r = commit(env, cr, ops, covers=["AC-1"])
    assert r.status_code == 422 and "你是不是想写 '$biz'" in r.json()["detail"]
    ops[1]["business"] = "$biz"  # 正确写法
    assert commit(env, cr, ops, covers=["AC-1"]).status_code == 200


# ---------- 新建的 key 在 MCP 里可以直接使用，不用重启 ----------


def test_use_api_key_switches_identity_without_restart(env, monkeypatch):
    import json as _json

    from speclock import mcp_server

    c = env["client"]
    admin_key = env["human"]["X-API-Key"]

    def fake_request(method, url, headers=None, timeout=None, **kw):
        return c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw)

    monkeypatch.setattr(mcp_server.httpx, "request", fake_request)
    monkeypatch.setattr(mcp_server, "CONFIGURED_KEY", admin_key)
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin_key)

    def call(raw):
        return _json.loads(raw)

    assert call(mcp_server.whoami())["body"]["role"] == "admin"

    # 管理员先创建 key（必须带人的原话），拿到明文后立刻切换，不用重启
    made = call(mcp_server.create_api_key("tester-agent", "qa", evidence="同意，建一把测试用的"))
    new_key = made["body"]["key"]
    switched = call(mcp_server.use_api_key(new_key))
    assert switched["switched"] is True and switched["identity"]["role"] == "tester-agent"
    assert call(mcp_server.whoami())["body"]["role"] == "tester-agent"
    # 测试 Agent 没有创建 key 的权限
    denied = call(mcp_server.create_api_key("executor-agent", "x", evidence="x"))
    assert denied["status"] == 403

    # 无效的 key：保持原身份不变
    bad = call(mcp_server.use_api_key("agent-not-a-real-key"))
    assert "error" in bad
    assert call(mcp_server.whoami())["body"]["role"] == "tester-agent"

    # 传空 = 回到配置的那把
    back = call(mcp_server.use_api_key(""))
    assert back["identity"]["role"] == "admin"
