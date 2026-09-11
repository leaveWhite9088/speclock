"""AI 接入（MCP）页：配置片段、8 工具清单、AI 最近活动表格。"""

from __future__ import annotations

import sys

from tests.conftest import publish_v1

ALL_TOOLS = [
    "get_documents", "get_document", "get_index", "get_block",
    "get_diff", "ack_block", "submit_proposal", "get_proposal",
]


def test_mcp_page_contains_config_snippet(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"/ui/mcp?key={env['human']['X-API-Key']}")
    assert r.status_code == 200
    body = r.text
    assert "mcpServers" in body
    assert "speclock.mcp_server" in body
    assert sys.executable in body  # command 用当前环境真实解释器路径
    assert "SPECLOCK_URL" in body and "SPECLOCK_KEY" in body
    assert env["agent"]["X-API-Key"] in body  # 配置里直接给出可用的 agent key
    assert "stdio" in body
    assert "复制" in body


def test_mcp_page_lists_all_8_tools(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    body = env["client"].get(f"/ui/mcp?key={env['human']['X-API-Key']}").text
    for tool in ALL_TOOLS:
        assert tool in body, tool
    assert "AI 可用工具清单（8 个）" in body


def test_mcp_page_shows_recent_agent_activity(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    # 制造几条 agent 活动
    c.get("/api/v1/index", headers=a)
    c.get(f"/api/v1/blocks/{bid}", headers=a)
    c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "1.0.0"}, headers=a)

    body = c.get(f"/ui/mcp?key={h['X-API-Key']}").text
    assert "pull" in body
    assert f"block:{bid}@1.0.0" in body
    assert "ack" in body
    assert "AI 最近活动" in body


def test_mcp_page_empty_activity(env):
    body = env["client"].get(f"/ui/mcp?key={env['human']['X-API-Key']}").text
    assert "暂无 AI 活动记录" in body


def test_nav_has_mcp_entry(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    body = env["client"].get(f"/ui?key={env['human']['X-API-Key']}").text
    assert "AI 接入" in body and "/ui/mcp" in body
