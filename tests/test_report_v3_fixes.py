"""联调报告 v3 确认的问题的回归测试。"""

from __future__ import annotations

import json
import re

import pytest

from speclock import home, keyfiles, mcp_server
from tests.conftest import commit, open_cr, publish_v1, req_key


@pytest.fixture()
def kh(env, tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    keyfiles.ensure_keys_dir(h)
    return h


@pytest.fixture()
def mcp(env, monkeypatch):
    c = env["client"]

    def fake_request(method, url, headers=None, timeout=None, **kw):
        return c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw)

    monkeypatch.setattr(mcp_server.httpx, "request", fake_request)
    return lambda raw: json.loads(raw)


# ---- V3-01：key 文件优先于环境变量里的 key ----


def test_key_file_wins_over_the_env_key(kh, monkeypatch):
    (kh / "keys" / "a--b.key").write_text("agent-from-file\n", encoding="utf-8")
    monkeypatch.setenv("SPECLOCK_KEY", "human-leaked-admin")  # 人在 shell 里为跑 CLI 随手设的
    monkeypatch.setenv("SPECLOCK_KEY_FILE", "a--b.key")
    key, source = mcp_server._configured()
    assert key == "agent-from-file" and "a--b.key" in source
    # 文件读不到：返回空，而不是退回到环境变量里那把更大权限的 key
    monkeypatch.setenv("SPECLOCK_KEY_FILE", "missing.key")
    assert mcp_server._configured()[0] == ""
    # 只有环境变量时照旧
    monkeypatch.delenv("SPECLOCK_KEY_FILE")
    assert mcp_server._configured() == ("human-leaked-admin", "环境变量 SPECLOCK_KEY")


def test_whoami_says_where_the_key_came_from(env, mcp, monkeypatch):
    admin = env["human"]["X-API-Key"]
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin)
    monkeypatch.setattr(mcp_server, "KEY_SOURCE", "key 文件 req--x.key")
    body = mcp(mcp_server.whoami())["body"]
    assert body["role"] == "admin" and body["key_source"] == "key 文件 req--x.key"


# ---- V3-03：use_api_key(key_file=) 只认 keys/ 里的文件名 ----


def test_strict_key_file_refuses_paths(kh):
    (kh / "web.key").write_text("human-web\n", encoding="utf-8")
    (kh / "keys" / "ok--x.key").write_text("agent-ok\n", encoding="utf-8")
    assert keyfiles.read_key("ok--x.key", kh, strict=True) == "agent-ok"
    assert keyfiles.read_key("ok--x", kh, strict=True) == "agent-ok"
    for bad in ("../web.key", "..", "../speclock.db", str(kh / "web.key"), "sub/x.key", "..\\web.key", ""):
        with pytest.raises((ValueError, FileNotFoundError)):
            keyfiles.read_key(bad, kh, strict=True)


def test_use_api_key_cannot_reach_files_outside_keys(env, kh, mcp, monkeypatch):
    (kh / "web.key").write_text("human-web\n", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "AGENT_KEY", env["agent"]["X-API-Key"])
    out = mcp(mcp_server.use_api_key(key_file="../web.key"))
    assert "error" in out and "不能带路径" in out["error"]
    assert mcp(mcp_server.whoami())["body"]["role"] == "executor-agent"  # 身份没变


# ---- V3-05：事后补覆盖 ----


def test_a_coverage_only_commit_can_be_added_afterwards(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cid = open_cr(env, acceptance=[{"name": "第一条", "detail": "甲"}, {"name": "第二条", "detail": "乙"}])
    ops = [{"op": "update_block", "id": env["block_id"], "summary": "新的摘要"}]
    assert commit(env, cid, ops, covers=["AC-1"]).status_code == 200
    # 补一条覆盖 AC-2（漏写了）：ops 为空，但要写明 covers 和原因
    assert commit(env, cid, [], covers=[]).status_code == 422
    assert commit(env, cid, [], covers=["AC-2"]).status_code == 422  # 没写原因
    r = c.post(f"/api/v1/change-requests/{cid}/commits",
               json={"ops": [], "covers": ["AC-2"], "change_note": "上一个 Commit 漏写了 AC-2，事后补覆盖"},
               headers=req_key(env))
    assert r.status_code == 200, r.text
    assert r.json()["blocks"] == []  # 没有改任何模块
    assert c.post(f"/api/v1/change-requests/{cid}/complete", headers=req_key(env)).json()["status"] == "applied"


# ---- V3-14：CLI 删除 key 的审计来源 ----


def test_cli_key_delete_is_audited_as_cli(env, monkeypatch, capsys):
    from speclock import cli
    from speclock.db import SessionLocal
    from speclock.models import AuditLog

    made = env["client"].post("/api/v1/keys", json={"role": "tester-agent", "label": "x", "via": "cli"},
                              headers=env["human"]).json()

    def fake_client(args):
        class _C:
            def request(self, method, path, **kw):
                return env["client"].request(method, path, headers=env["human"], **kw)
        return _C(), "x"

    monkeypatch.setattr(cli, "_client", fake_client)
    cli.main(["key", "delete", str(made["id"])])
    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "key_delete").order_by(AuditLog.id.desc()).first()
        assert json.loads(row.detail_json)["via"] == "cli"
    finally:
        db.close()


# ---- V3-09：说明数据目录是怎么找到的 ----


def test_locate_home_says_how_it_was_found(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECLOCK_HOME", raising=False)
    monkeypatch.setenv("SPECLOCK_GLOBAL_HOME", str(tmp_path / "g" / ".speclock"))
    proj = tmp_path / "proj"
    (proj / "sub" / "deeper").mkdir(parents=True)
    home.write_home(proj / ".speclock", 1234)
    found, how = home.locate_home(proj)
    assert found == proj / ".speclock" and how == "当前目录"
    found, how = home.locate_home(proj / "sub" / "deeper")
    assert found == proj / ".speclock" and how.startswith("上层目录")  # 启动时会提醒
    monkeypatch.setenv("SPECLOCK_HOME", str(tmp_path / "x"))
    assert home.locate_home(proj)[1] == "环境变量 SPECLOCK_HOME"


# ---- V3-10：--new-admin 的说明与 --revoke-old ----


def test_new_admin_can_revoke_the_old_admin_keys(tmp_path, monkeypatch, capsys):
    from speclock import cli, db as dbmod
    from speclock.auth import hash_key
    from speclock.models import ApiKey

    monkeypatch.delenv("SPECLOCK_HOME", raising=False)
    monkeypatch.setenv("SPECLOCK_GLOBAL_HOME", str(tmp_path / "g" / ".speclock"))
    proj = tmp_path / "p"
    proj.mkdir()
    monkeypatch.chdir(proj)
    try:
        cli.main(["init"])
        first = re.search(r"human-[0-9a-f]{32}", capsys.readouterr().out).group(0)
        cli.main(["init", "--new-admin"])
        out = capsys.readouterr().out
        assert "仍然有效" in out and "--revoke-old" in out and "下一步" not in out
        cli.main(["init", "--new-admin", "--revoke-old"])
        out = capsys.readouterr().out
        newest = re.search(r"human-[0-9a-f]{32}", out).group(0)
        assert "已吊销旧的 admin key：2 把" in out
        db = dbmod.SessionLocal()
        try:
            admins = [k.key for k in db.query(ApiKey).all() if k.role and k.role.name == "admin"]
        finally:
            db.close()
        assert admins == [hash_key(newest)] and hash_key(first) not in admins
    finally:
        dbmod.configure(__import__("os").environ["SPECLOCK_DB_URL"])


# ---- V3-04：MCP 工具参数拼错要报错 ----


def test_mcp_tools_reject_unknown_arguments():
    import asyncio

    async def call(name, args):
        return await mcp_server.mcp.call_tool(name, args)

    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        asyncio.run(call("create_change_request", {"title": "x", "acceptence": []}))  # 拼错的 acceptance


# ---- V3-11：绑定项目的 key 在别的项目开单，说人话 ----


def test_creating_a_request_in_another_project_explains_itself(env):
    r = env["client"].post("/api/v1/change-requests", json={"title": "x", "intent": "x", "expected_outcome": "x",
                           "acceptance": [{"name": "a", "detail": "b"}], "project_id": 999}, headers=req_key(env))
    assert r.status_code == 404 and "没有项目 999" in r.json()["detail"]
    from speclock.db import SessionLocal
    from speclock.models import Project

    db = SessionLocal()
    try:
        other = Project(name="另一个项目")
        db.add(other)
        db.commit()
        other_id = other.id
    finally:
        db.close()
    r = env["client"].post("/api/v1/change-requests", json={"title": "x", "intent": "x", "expected_outcome": "x",
                           "acceptance": [{"name": "a", "detail": "b"}], "project_id": other_id}, headers=req_key(env))
    assert r.status_code == 404 and "绑定在项目" in r.json()["detail"] and "change request" not in r.text


# ---- V3-13：请求体编码错误的提示 ----


def test_a_broken_json_body_says_to_use_utf8(env):
    r = env["client"].post("/api/v1/change-requests", content=b"{\"title\": \"\xd6\xd0\xce\xc4\"}",
                           headers={**req_key(env), "Content-Type": "application/json"})
    assert r.status_code in (400, 422)
    if r.status_code == 400:
        assert "UTF-8" in r.json()["detail"]
