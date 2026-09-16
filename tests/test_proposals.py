"""Proposal channel: submit -> human approves -> merged into a new version."""

from __future__ import annotations

from tests.conftest import APIS_INVALID_TYPE, APIS_V2_MINOR, publish_v1


def _submit(env, **overrides):
    body = {
        "block_id": env["block_id"],
        "description": "采集状态接口缺少备注字段，前端无法展示运营说明",
        "suggestion": "响应体增加 extra_note 字段",
        "scenario": "前端开发日报页时发现，src/pages/daily.tsx:42",
        "proposed_apis": APIS_V2_MINOR,
    }
    body.update(overrides)
    return env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])


def test_full_proposal_lifecycle(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)

    # agent submits
    r = _submit(env)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "submitted"

    # proposal does NOT change what agents read
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["version"] == "1.0.0"

    # agent can poll status
    assert c.get(f"/api/v1/proposals/{pid}", headers=a).json()["status"] == "submitted"

    # human sees it in the inbox and approves -> publishes new version
    inbox = c.get("/api/v1/proposals", headers=h).json()
    assert any(p["id"] == pid and p["status"] == "submitted" for p in inbox)
    r = c.post(f"/api/v1/proposals/{pid}/resolve",
               json={"action": "approve", "resolution_note": "合理，加字段"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["published_version"] == "1.1.0"
    assert r.json()["document_version"] == "1.1.0"  # 文档版本同步派生

    # agent now reads the merged new version
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.json()["version"] == "1.1.0"
    assert any(f["name"] == "extra_note" for f in r.json()["apis"][0]["response"])

    # and the poll reflects the outcome
    p = c.get(f"/api/v1/proposals/{pid}", headers=a).json()
    assert p["status"] == "published"
    assert p["published_version"] == "1.1.0"


def test_reject_proposal(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    pid = _submit(env).json()["id"]
    r = c.post(f"/api/v1/proposals/{pid}/resolve",
               json={"action": "reject", "resolution_note": "备注走另一个接口"}, headers=h)
    assert r.status_code == 200
    p = c.get(f"/api/v1/proposals/{pid}", headers=a).json()
    assert p["status"] == "rejected"
    assert p["resolution_note"] == "备注走另一个接口"
    # block untouched
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["version"] == "1.0.0"


def test_cannot_resolve_twice(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    pid = _submit(env).json()["id"]
    c.post(f"/api/v1/proposals/{pid}/resolve", json={"action": "reject"}, headers=h)
    r = c.post(f"/api/v1/proposals/{pid}/resolve", json={"action": "approve"}, headers=h)
    assert r.status_code == 409


def test_proposal_with_invalid_apis_rejected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit(env, proposed_apis=APIS_INVALID_TYPE)
    assert r.status_code == 422


def test_proposal_targets_must_be_published_blocks(env):
    r = _submit(env)  # block still a draft
    assert r.status_code == 404


def test_proposals_are_audited(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    pid = _submit(env).json()["id"]
    c.post(f"/api/v1/proposals/{pid}/resolve", json={"action": "approve"}, headers=h)
    from speclock.db import SessionLocal
    from speclock.models import AuditLog

    db = SessionLocal()
    actions = [log.action for log in db.query(AuditLog).all()]
    db.close()
    assert "proposal_submit" in actions
    assert "proposal_resolve" in actions


def test_admin_proposal_list_includes_proposed_fields(env):
    """SPA 审核队列（ProposalsView）依赖列表直接带改写内容，不再二次请求。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    pid = _submit(env, proposed_content_md="# 数据采集模块\n\n改写后的叙述。").json()["id"]

    inbox = c.get("/api/v1/proposals", headers=h).json()
    p = next(p for p in inbox if p["id"] == pid)
    assert p["proposed_content_md"] == "# 数据采集模块\n\n改写后的叙述。"
    # proposed_apis 经规范化（补齐 children 等），断言语义内容
    assert [a["name"] for a in p["proposed_apis"]] == [a["name"] for a in APIS_V2_MINOR]
    assert p["proposed_apis"][0]["response"][-1]["name"] == "extra_note"


def test_admin_proposal_list_proposed_fields_nullable(env):
    """只提建议不带改写的提案：两个 proposed 字段为 null 而不是缺失。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    pid = _submit(env, proposed_apis=None).json()["id"]

    p = next(p for p in c.get("/api/v1/proposals", headers=h).json() if p["id"] == pid)
    assert p["proposed_content_md"] is None
    assert p["proposed_apis"] is None


def test_agent_get_proposal_echoes_proposed_fields(env):
    """agent 轮询单条提案时也能拿回自己提交的改写内容（与提交时一致）。"""
    c, a = env["client"], env["agent"]
    publish_v1(c, env["human"], env["block_id"])
    pid = _submit(env, proposed_content_md="# 改写").json()["id"]

    p = c.get(f"/api/v1/proposals/{pid}", headers=a).json()
    assert p["proposed_content_md"] == "# 改写"
    assert [a["name"] for a in p["proposed_apis"]] == [a["name"] for a in APIS_V2_MINOR]
    assert p["proposed_apis"][0]["response"][-1]["name"] == "extra_note"
