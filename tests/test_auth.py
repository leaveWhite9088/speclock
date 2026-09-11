"""S1 acceptance: an agent key is technically unable to modify published docs.

Every write endpoint in the system is enumerated here and must reject the
agent key with 403 (and no key with 401). If a new write endpoint is ever
added, this test must grow with it.
"""

from __future__ import annotations

from tests.conftest import publish_v1

# Every write (mutating) endpoint in the system. Agent key -> 403, always.
WRITE_ENDPOINTS = [
    ("POST", "/api/v1/projects", {"name": "x"}),
    ("POST", "/api/v1/domains", {"project_id": 1, "name": "x"}),
    ("PUT", "/api/v1/domains/1", {"name": "x"}),
    ("DELETE", "/api/v1/domains/1", None),
    ("POST", "/api/v1/documents", {"domain_id": 1, "title": "x"}),
    ("PUT", "/api/v1/documents/1", {"name": "x"}),
    ("DELETE", "/api/v1/documents/1", None),
    ("POST", "/api/v1/blocks", {"document_id": 1, "title": "x"}),
    ("PUT", "/api/v1/blocks/1", {"title": "hacked"}),
    ("DELETE", "/api/v1/blocks/1", None),
    ("POST", "/api/v1/blocks/1/restore", None),
    ("DELETE", "/api/v1/blocks/1/purge", None),
    ("POST", "/api/v1/blocks/1/complete", None),
    ("POST", "/api/v1/blocks/1/uncomplete", None),
    ("POST", "/api/v1/blocks/1/publish", {"change_note": "x", "fastTrack": True}),
    ("POST", "/api/v1/proposals/1/resolve", {"action": "approve"}),
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


def test_unknown_key_rejected(env):
    r = env["client"].get("/api/v1/index", headers={"X-API-Key": "agent-doesnotexist"})
    assert r.status_code == 401


def test_human_key_cannot_use_agent_read_api(env):
    """The boundary is two-way: human keys are not valid agent credentials."""
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get("/api/v1/index", headers=env["human"])
    assert r.status_code == 403


def test_agent_key_reads_published_block(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"])
    assert r.status_code == 200
