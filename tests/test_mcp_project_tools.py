"""MCP 补齐的工具：项目、活动日志；以及 CLI 的 project 命令。
（搜索和已归档模块不给 Agent：Agent 从索引逐层定位，归档内容本来就不让它看到。）"""

from __future__ import annotations

import json

import pytest

from speclock import mcp_server
from tests.conftest import publish_v1


@pytest.fixture()
def mcp(env, monkeypatch):
    c = env["client"]

    def fake_request(method, url, headers=None, timeout=None, **kw):
        return c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw)

    admin = env["human"]["X-API-Key"]
    monkeypatch.setattr(mcp_server.httpx, "request", fake_request)
    monkeypatch.setattr(mcp_server, "CONFIGURED_KEY", admin)
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin)
    return lambda raw: json.loads(raw)


def test_list_create_and_rename_project(env, mcp):
    before = mcp(mcp_server.list_projects())
    assert before["status"] == 200 and before["body"]  # 测试里的 key 绑定了项目 1，只看得到它
    made = mcp(mcp_server.create_project("新项目"))
    assert made["status"] == 201 and made["body"]["name"] == "新项目"
    pid = made["body"]["id"]
    renamed = mcp(mcp_server.rename_project(pid, "改了名"))
    assert renamed["status"] == 200 and renamed["body"]["name"] == "改了名"


def test_project_tools_need_project_manage(env, mcp):
    mcp_server.AGENT_KEY = env["agent"]["X-API-Key"]  # 执行 Agent
    assert mcp(mcp_server.create_project("偷偷建"))["status"] == 403
    assert mcp(mcp_server.rename_project(1, "x"))["status"] == 403
    assert mcp(mcp_server.list_projects())["status"] == 200  # 读是可以的


def test_activity_log_filters_and_paging(env, mcp):
    publish_v1(env["client"], env["human"], env["block_id"])
    rows = mcp(mcp_server.get_activity(limit=5))
    assert rows["status"] == 200 and 1 <= len(rows["body"]) <= 5
    name = rows["body"][0]["action"]
    only = mcp(mcp_server.get_activity(action=name))["body"]
    assert only and all(r["action"] == name for r in only)
    assert all(r["action"] != name for r in mcp(mcp_server.get_activity(exclude_action=name))["body"])
    older = mcp(mcp_server.get_activity(before_id=rows["body"][0]["id"], limit=5))["body"]
    assert all(r["id"] < rows["body"][0]["id"] for r in older)


def test_activity_needs_audit_read(env, mcp):
    mcp_server.AGENT_KEY = env["agent"]["X-API-Key"]
    assert mcp(mcp_server.get_activity())["status"] == 403


def test_cli_project_commands(env, monkeypatch, capsys):
    from speclock import cli

    c = env["client"]
    import httpx

    class _Client(httpx.Client):  # 把 CLI 的请求转给 TestClient
        pass

    def fake_client(args):
        class _C:
            def request(self, method, path, **kw):
                return c.request(method, path, headers=env["human"], **kw)
        return _C(), "x"

    monkeypatch.setattr(cli, "_client", fake_client)
    cli.main(["project", "create", "命令行建的"])
    cli.main(["project", "list"])
    out = capsys.readouterr().out
    assert "已创建项目" in out and "命令行建的" in out
