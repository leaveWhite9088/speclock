"""AI 接入页的后端数据源：GET /api/v1/activity（审计日志，按 actor 前缀过滤）。

页面本身已由 Vue SPA 渲染（McpView.vue，配置片段在浏览器侧按
window.location.origin 生成），服务端只需提供活动数据。"""

from __future__ import annotations

from tests.conftest import publish_v1


def test_activity_lists_recent_agent_activity(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.get("/api/v1/index", headers=a)
    c.get(f"/api/v1/blocks/{bid}", headers=a)
    c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "1.0.0"}, headers=a)

    rows = c.get("/api/v1/activity", headers=h).json()
    actions = [r["action"] for r in rows]
    assert "pull" in actions and "ack" in actions
    targets = [r["target"] for r in rows]
    assert f"block:{bid}@1.0.0" in targets
    # 新的在前：最后一条审计（ack）排最前
    assert rows[0]["action"] == "ack"


def test_activity_filter_by_actor_prefix(env):
    """SPA 的 AI 接入页用 actor_prefix=agent 只看 AI 活动。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.get("/api/v1/index", headers=a)

    rows = c.get("/api/v1/activity", params={"actor_prefix": "agent"}, headers=h).json()
    assert rows and all(r["actor"].startswith("agent-") for r in rows)
    assert all(r["action"] in ("pull", "ack", "proposal_submit") for r in rows)


def test_activity_empty(env):
    rows = env["client"].get("/api/v1/activity", headers=env["human"]).json()
    assert rows == []


def test_activity_requires_human_key(env):
    c, a = env["client"], env["agent"]
    assert c.get("/api/v1/activity").status_code == 401
    assert c.get("/api/v1/activity", headers=a).status_code == 403
