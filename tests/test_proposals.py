"""Proposal channel: submit -> human approves -> merged into a new version."""

from __future__ import annotations

from tests.conftest import VALID_YAML_V2_MINOR, publish_v1


def _submit(env, **overrides):
    body = {
        "block_id": env["block_id"],
        "description": "日报主表缺少备注字段，前端无法展示运营说明",
        "suggestion": "在 DailyReportRow 增加 extra_note 字段",
        "scenario": "前端开发日报页时发现，src/pages/daily.tsx:42",
        "proposed_openapi_yaml": VALID_YAML_V2_MINOR,
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

    # agent now reads the merged new version
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.json()["version"] == "1.1.0"
    assert "extra_note" in r.json()["openapi_yaml"]

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


def test_proposal_with_invalid_yaml_rejected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit(env, proposed_openapi_yaml="openapi: 2.0\npaths: 42\n")
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
