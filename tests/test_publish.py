"""Publish flow: version auto-increment, fastTrack rules, draft invisibility."""

from __future__ import annotations

from tests.conftest import (
    INVALID_YAML,
    VALID_YAML_V2_BREAKING,
    VALID_YAML_V2_MINOR,
    publish_v1,
)


def test_first_publish_is_1_0_0(env):
    r = publish_v1(env["client"], env["human"], env["block_id"])
    assert r["version"] == "1.0.0"
    assert r["delta"]["added"]  # everything is new on first publish
    assert r["breaking"] is False  # no prior version -> nothing can be removed


def test_added_field_bumps_minor_and_allows_fasttrack(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": VALID_YAML_V2_MINOR}, headers=h)
    assert r.status_code == 200
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "加字段", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.1.0"
    assert body["breaking"] is False
    assert any("extra_note" in a for a in body["delta"]["added"])


def test_breaking_change_rejects_fasttrack_and_requires_confirm(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": VALID_YAML_V2_BREAKING}, headers=h)

    # fastTrack must be refused
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "改类型", "fastTrack": True}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["breaking"] is True
    assert any("id" in a for a in r.json()["detail"]["affected"])

    # no confirm -> also refused, with affected list
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "改类型"}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["affected"]

    # confirm -> publishes as MAJOR bump
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "改类型", "confirm": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "2.0.0"
    assert r.json()["breaking"] is True


def test_removed_field_is_breaking(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    c, h, bid = env["client"], env["human"], env["block_id"]
    yaml_removed = VALID_YAML_V2_BREAKING.replace("        name: {type: string}\n", "")
    c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": yaml_removed}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish", json={"change_note": "删字段"}, headers=h)
    assert r.status_code == 409
    assert any("name" in a for a in r.json()["detail"]["affected"])


def test_invalid_openapi_cannot_be_saved_or_published(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": INVALID_YAML}, headers=h)
    assert r.status_code == 422


def test_draft_invisible_to_agent(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    # block exists only as a draft
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.status_code == 404
    r = c.get("/api/v1/index", headers=a)
    assert r.status_code == 200
    assert r.json() == []
    # after publish it becomes visible
    publish_v1(c, h, bid)
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 200


def test_delta_stored_on_version(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": VALID_YAML_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "x", "fastTrack": True}, headers=h)
    r = c.get(f"/api/v1/blocks/{bid}@1.1.0", headers=env["agent"])
    assert r.status_code == 200
    delta = r.json()["delta"]
    assert any("extra_note" in a for a in delta["added"])
    assert delta["removed"] == []
