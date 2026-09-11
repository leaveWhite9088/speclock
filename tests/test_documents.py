"""Document-level versioning: derived from module publishes, and the
agent-side document endpoints."""

from __future__ import annotations

from tests.conftest import (
    APIS_V1,
    APIS_V2_BREAKING,
    APIS_V2_MINOR,
    create_module,
    publish_v1,
)


def test_document_version_derives_from_module_publishes(env):
    c, h, bid, did = env["client"], env["human"], env["block_id"], env["document_id"]

    # first module publish -> doc 1.0.0
    r = publish_v1(c, h, bid)
    assert r["document_version"] == "1.0.0"

    # second module's first publish -> doc MINOR bump
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    r = publish_v1(c, h, bid2)
    assert r["version"] == "1.0.0"
    assert r["document_version"] == "1.1.0"

    # minor change on module 1 -> doc MINOR bump, module 2 untouched
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "加字段", "fastTrack": True}, headers=h).json()
    assert r["version"] == "1.1.0"
    assert r["document_version"] == "1.2.0"

    # breaking change on module 1 -> doc MAJOR bump
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_BREAKING}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "改类型", "confirm": True}, headers=h).json()
    assert r["version"] == "2.0.0"
    assert r["document_version"] == "2.0.0"

    # module 2 never republished: still 1.0.0
    versions = c.get(f"/api/v1/blocks/{bid2}/versions", headers=h).json()
    assert [v["version"] for v in versions] == ["1.0.0"]


def test_document_manifest_content(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    publish_v1(c, h, bid)
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    publish_v1(c, h, bid2)
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "加字段", "fastTrack": True}, headers=h)

    r = c.get(f"/api/v1/documents/{did}", headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.2.0"
    manifest = {m["block_id"]: m["version"] for m in body["manifest"]}
    assert manifest == {bid: "1.1.0", bid2: "1.0.0"}

    # pin an old document version -> historical manifest replay
    r = c.get(f"/api/v1/documents/{did}@1.0.0", headers=a)
    assert r.status_code == 200
    manifest = {m["block_id"]: m["version"] for m in r.json()["manifest"]}
    assert manifest == {bid: "1.0.0"}  # bid2 not yet published at doc 1.0.0


def test_documents_index_for_agent(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    # document without any published module is invisible to agents
    assert c.get("/api/v1/documents", headers=a).json() == []
    assert c.get(f"/api/v1/documents/{did}", headers=a).status_code == 404

    publish_v1(c, h, bid)
    r = c.get("/api/v1/documents", headers=a)
    assert r.status_code == 200
    entry = r.json()[0]
    assert entry["document_id"] == did
    assert entry["version"] == "1.0.0"
    assert entry["title"] == "经营日报"
    assert entry["domain"] == "运营"


def test_document_version_pin_missing_version_404(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    publish_v1(c, h, bid)
    assert c.get(f"/api/v1/documents/{did}@9.9.9", headers=a).status_code == 404
