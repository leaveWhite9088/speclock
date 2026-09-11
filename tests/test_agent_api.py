"""Agent read API: index size contract, version pin semantics, ack receipts."""

from __future__ import annotations

from tests.conftest import VALID_YAML_V2_MINOR, publish_v1


def test_index_is_one_line_per_block_and_small(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get("/api/v1/index", headers=env["agent"])
    assert r.status_code == 200
    # NF-1: index body must stay <= 8KB
    assert len(r.content) <= 8192
    entry = r.json()[0]
    assert set(entry) == {"block_id", "title", "domain", "document", "version", "summary"}
    assert len(entry["summary"]) <= 50
    assert entry["version"] == "1.0.0"


def test_version_pin_reads_exact_snapshot(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    # publish a second version with different content
    c.put(f"/api/v1/blocks/{bid}",
          json={"content_md": "# 日报主表 v2\n\n新版描述。",
                "openapi_yaml": VALID_YAML_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)

    # unpinned -> latest
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.json()["version"] == "1.1.0"
    assert "新版描述" in r.json()["content_md"]

    # pinned -> exact old snapshot, still replayable (S4)
    r = c.get(f"/api/v1/blocks/{bid}@1.0.0", headers=a)
    assert r.status_code == 200
    assert r.json()["version"] == "1.0.0"
    assert "新版描述" not in r.json()["content_md"]

    # pin a version that does not exist
    assert c.get(f"/api/v1/blocks/{bid}@9.9.9", headers=a).status_code == 404


def test_diff_between_published_versions(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.put(f"/api/v1/blocks/{bid}", json={"openapi_yaml": VALID_YAML_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    r = c.get(f"/api/v1/blocks/{bid}/diff", params={"from": "1.0.0", "to": "1.1.0"}, headers=a)
    assert r.status_code == 200
    body = r.json()
    assert any("extra_note" in x for x in body["delta"]["added"])
    assert body["breaking"] is False
    assert "extra_note" in body["openapi_diff"]


def test_ack_receipt_roundtrip(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    r = c.post(f"/api/v1/blocks/{bid}/ack",
               json={"version": "1.0.0", "task_desc": "实现日报主表前端"}, headers=a)
    assert r.status_code == 201
    # acking an unpublished version is rejected
    r = c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "3.0.0"}, headers=a)
    assert r.status_code == 404
    # human sees the ack on the board
    r = c.get("/api/v1/acks", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["version"] == "1.0.0"
    assert rows[0]["task_desc"] == "实现日报主表前端"


def test_pulls_are_audited(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.get(f"/api/v1/blocks/{bid}", headers=a)
    from speclock.db import SessionLocal
    from speclock.models import AuditLog

    db = SessionLocal()
    actions = [log.action for log in db.query(AuditLog).all()]
    db.close()
    assert "publish" in actions
    assert "pull" in actions
