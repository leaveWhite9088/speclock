"""权限边界：agent 类 key 永远改不了规格；规格库没有任何"直接写"接口。

- 每个仍然存在的写（改动）接口：缺 key → 401，agent key → 403；
- 旧的直接写入口（建模块 / 改草稿 / 发布 / 提案批准……）整个不存在，连管理员 key 也是 404 / 405；
- 没有 cr.approve 的角色批准不了审核单——agent 类角色根本挂不上这条权限。
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    approve_cr,
    cr_body,
    make_key,
    open_cr,
    publish_v1,
    req_key,
    reviewer_key,
)

# 仍然存在的写接口。executor agent key -> 403，不带 key -> 401。
WRITE_ENDPOINTS = [
    ("POST", "/api/v1/projects", {"name": "x"}),
    ("PUT", "/api/v1/projects/1", {"name": "x"}),
    ("DELETE", "/api/v1/projects/1", None),
    ("POST", "/api/v1/keys", {"role": "admin"}),
    ("DELETE", "/api/v1/keys/1", None),
    ("POST", "/api/v1/roles", {"name": "x", "kind": "agent"}),
    ("PUT", "/api/v1/roles/1", {"description": "x"}),
    ("DELETE", "/api/v1/roles/1", None),
    ("POST", "/api/v1/change-requests", cr_body()),
    ("PUT", "/api/v1/change-requests/1", {"title": "x"}),
    ("POST", "/api/v1/change-requests/1/submit", None),
    ("POST", "/api/v1/change-requests/1/withdraw", None),
    ("POST", "/api/v1/change-requests/1/approve", {"content_hash": "x"}),
    ("POST", "/api/v1/change-requests/1/reject", {"reason": "x"}),
    ("POST", "/api/v1/change-requests/1/commits", {"ops": [{"op": "archive_block", "id": 1}]}),
    ("POST", "/api/v1/change-requests/1/complete", None),
]

# 被整个移除的旧入口：连管理员 key 也不能用（路径不存在或方法不允许）。
REMOVED_ENDPOINTS = [
    ("POST", "/api/v1/businesses"),
    ("PUT", "/api/v1/businesses/1"),
    ("DELETE", "/api/v1/businesses/1"),
    ("POST", "/api/v1/capabilities"),
    ("PUT", "/api/v1/capabilities/1"),
    ("DELETE", "/api/v1/capabilities/1"),
    ("POST", "/api/v1/blocks"),
    ("PUT", "/api/v1/blocks/1"),
    ("DELETE", "/api/v1/blocks/1"),
    ("GET", "/api/v1/blocks/1/draft"),
    ("POST", "/api/v1/blocks/1/restore"),
    ("DELETE", "/api/v1/blocks/1/purge"),
    ("POST", "/api/v1/blocks/1/publish"),
    ("GET", "/api/v1/proposals"),
    ("POST", "/api/v1/proposals"),
    ("POST", "/api/v1/proposals/1/resolve"),
    ("POST", "/api/v1/blocks/1/versions/1.0.0/void"),  # 作废已删除：修正走审核单
    ("POST", "/api/v1/blocks/1/ack"),  # 实现回执已被执行记录取代
    ("GET", "/api/v1/acks"),
]


def test_agent_key_rejected_on_all_write_endpoints(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    for method, path, body in WRITE_ENDPOINTS:
        kwargs = {"headers": env["agent"]}
        if body is not None:
            kwargs["json"] = body
        r = env["client"].request(method, path, **kwargs)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}: {r.text}"


def test_missing_key_rejected_on_all_write_endpoints(env):
    for method, path, body in WRITE_ENDPOINTS:
        kwargs = {}
        if body is not None:
            kwargs["json"] = body
        r = env["client"].request(method, path, **kwargs)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.parametrize("method,path", REMOVED_ENDPOINTS)
def test_direct_write_endpoints_are_gone(env, method, path):
    """规格库只有「审核单 → Commit」一条写入通道：旧的直接写入口整个不存在。"""
    r = env["client"].request(method, path, headers=env["human"], json={})
    assert r.status_code in (404, 405), f"{method} {path} -> {r.status_code}: {r.text}"


def test_unknown_key_rejected(env):
    r = env["client"].get("/api/v1/index", headers={"X-API-Key": "agent-doesnotexist"})
    assert r.status_code == 401


def test_requirements_agent_cannot_approve(env):
    """需求 Agent 能建单、提交，但批准会被 403——Agent 本身就批准不了任何东西。"""
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    cr = c.get(f"/api/v1/change-requests/{cr_id}", headers=req_key(env)).json()
    r = c.post(f"/api/v1/change-requests/{cr_id}/approve",
               json={"content_hash": cr["content_hash"]}, headers=req_key(env))
    assert r.status_code == 403 and "cr.approve" in r.json()["detail"]
    r = c.post(f"/api/v1/change-requests/{cr_id}/reject",
               json={"reason": "x"}, headers=req_key(env))
    assert r.status_code == 403
    assert c.get(f"/api/v1/change-requests/{cr_id}", headers=req_key(env)).json()["status"] == "pending_review"


def test_reviewer_can_approve_but_cannot_write(env):
    """审核人只能批准 / 驳回：不能建单，也不能提交 Commit。"""
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    rev = reviewer_key(env)
    r = c.post("/api/v1/change-requests", json=cr_body(), headers=rev)
    assert r.status_code == 403
    r = c.post(f"/api/v1/change-requests/{cr_id}/commits",
               json={"ops": [{"op": "archive_block", "id": 1}]}, headers=rev)
    assert r.status_code == 403
    approve_cr_as(env, cr_id, rev)


def approve_cr_as(env, cr_id, headers):
    c = env["client"]
    cr = c.get(f"/api/v1/change-requests/{cr_id}", headers=headers).json()
    r = c.post(f"/api/v1/change-requests/{cr_id}/approve",
               json={"content_hash": cr["content_hash"], "via": "button"}, headers=headers)
    assert r.status_code == 200, r.text


def test_human_key_with_spec_read_can_read_but_scanner_cannot_claim(env):
    """读规格看角色权限，不看 key 前缀：admin 有 spec.read 所以能读 /index；
    没有 exec.write 的角色领任务会 403。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    c = env["client"]
    assert c.get("/api/v1/index", headers=env["human"]).status_code == 200
    scanner = make_key(env, "scanner-agent")
    work_id = c.get("/api/v1/work", headers=env["human"]).json()[0]["id"]
    assert c.post(f"/api/v1/work/{work_id}/claim", headers=scanner).status_code == 403
    assert c.get("/api/v1/work", headers=scanner).status_code == 200  # 能看进展，但不能动手
