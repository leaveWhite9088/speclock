"""SPA human read endpoints: /tree, /blocks/{id}/versions/{v}, /blocks/{id}/diff,
/archive, /activity — auth boundary, structure, filters.

Note: /blocks/{id}/diff is one physical route shared by humans and agents
(see api_agent.get_diff): agent keys keep their published-only + project-scope
semantics, so they are NOT 403 here; the other four are human-only (403).
"""

from __future__ import annotations

import pytest

from tests.conftest import APIS_V2_MINOR, create_module, publish_v1

HUMAN_ONLY_READS = [
    "/api/v1/tree",
    "/api/v1/blocks/1/versions/1.0.0",
    "/api/v1/archive",
    "/api/v1/activity",
]


def _publish_v2_minor(env, block_id):
    c, h = env["client"], env["human"]
    r = c.put(f"/api/v1/blocks/{block_id}", json={"apis": APIS_V2_MINOR}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post(
        f"/api/v1/blocks/{block_id}/publish",
        json={"change_note": "v2", "fastTrack": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------- auth boundary ----------


@pytest.mark.parametrize("path", HUMAN_ONLY_READS)
def test_human_only_reads_reject_agent_key(env, path):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(path, headers=env["agent"])
    assert r.status_code == 403, f"{path} -> {r.status_code}: {r.text}"


@pytest.mark.parametrize("path", HUMAN_ONLY_READS)
def test_human_only_reads_reject_missing_key(env, path):
    r = env["client"].get(path)
    assert r.status_code == 401, f"{path} -> {r.status_code}: {r.text}"


def test_diff_rejects_missing_key(env):
    r = env["client"].get(f"/api/v1/blocks/{env['block_id']}/diff")
    assert r.status_code == 401


# ---------- GET /api/v1/tree ----------


def test_tree_structure(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    draft_id = create_module(c, h, env["document_id"], "草稿模块")

    r = c.get("/api/v1/tree", headers=h)
    assert r.status_code == 200
    tree = r.json()
    assert len(tree) == 1
    project = tree[0]
    assert project["id"] == env["project_id"] and project["name"] == "测试项目"

    domain = project["domains"][0]
    assert domain["id"] == env["domain_id"] and domain["name"] == "运营"

    document = domain["documents"][0]
    assert document["id"] == env["document_id"]
    assert document["title"] == "经营日报"
    assert document["doc_type"] == "business"
    assert document["current_version"] is not None

    blocks = {b["id"]: b for b in document["blocks"]}
    published = blocks[env["block_id"]]
    assert published["title"] == "数据采集模块"
    assert published["status"] == "published"
    assert published["current_published_version"] == "1.0.0"
    assert published["completed"] is False
    draft = blocks[draft_id]
    assert draft["status"] == "draft"
    assert draft["current_published_version"] is None


# ---------- GET /api/v1/blocks/{id}/versions/{version} ----------


def test_version_snapshot_full_fields(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)

    r = c.get(f"/api/v1/blocks/{bid}/versions/1.0.0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["block_id"] == bid
    assert body["version"] == "1.0.0"
    assert body["title"] == "数据采集模块"
    assert body["status"] == "published"
    assert "数据采集模块" in body["content_md"]
    assert body["rules"][0]["name"] == "销售额口径"
    assert body["apis"][0]["api"] == "GET /api/daily-report"
    assert "openapi" in body["openapi_yaml"]
    assert body["nfr_md"]
    assert body["change_note"] == "v1"
    assert body["published_by"].startswith("human-")
    assert body["published_at"] is not None
    assert "delta" in body


def test_version_snapshot_404(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    assert c.get("/api/v1/blocks/9999/versions/1.0.0", headers=h).status_code == 404
    assert c.get(f"/api/v1/blocks/{bid}/versions/9.9.9", headers=h).status_code == 404


# ---------- GET /api/v1/blocks/{id}/diff ----------


def test_diff_human_defaults_to_last_two_versions(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _publish_v2_minor(env, bid)

    r = c.get(f"/api/v1/blocks/{bid}/diff", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["block_id"] == bid
    assert body["from"] == "1.0.0" and body["to"] == "1.1.0"
    assert any("extra_note" in x for x in body["delta"]["added"])
    assert body["breaking"] is False
    assert "content_diff" in body and "openapi_diff" in body


def test_diff_human_explicit_from_to(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _publish_v2_minor(env, bid)

    r = c.get(f"/api/v1/blocks/{bid}/diff",
              params={"from": "1.1.0", "to": "1.0.0"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "1.1.0" and body["to"] == "1.0.0"
    assert any("extra_note" in x for x in body["delta"]["removed"])


def test_diff_single_version_friendly_message(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    r = c.get(f"/api/v1/blocks/{bid}/diff", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "暂无可对比" in body["message"]
    assert body["versions"] == ["1.0.0"]


def test_diff_unknown_block_and_version_404(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _publish_v2_minor(env, bid)
    assert c.get("/api/v1/blocks/9999/diff", headers=h).status_code == 404
    r = c.get(f"/api/v1/blocks/{bid}/diff",
              params={"from": "9.9.9", "to": "1.1.0"}, headers=h)
    assert r.status_code == 404


def test_diff_dual_auth_agent_published_only_human_sees_archived(env):
    """Shared route: agent key keeps published-only semantics (archived → 404);
    human key can still diff an archived block's history."""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    _publish_v2_minor(env, bid)

    assert c.get(f"/api/v1/blocks/{bid}/diff", headers=a).status_code == 200

    r = c.delete(f"/api/v1/blocks/{bid}", headers=h)  # archive
    assert r.status_code == 200 and r.json()["status"] == "archived"

    assert c.get(f"/api/v1/blocks/{bid}/diff", headers=a).status_code == 404
    r = c.get(f"/api/v1/blocks/{bid}/diff", headers=h)
    assert r.status_code == 200
    assert r.json()["from"] == "1.0.0" and r.json()["to"] == "1.1.0"


# ---------- GET /api/v1/archive ----------


def test_archive_list_empty_then_populated(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    assert c.get("/api/v1/archive", headers=h).json() == []

    publish_v1(c, h, bid)
    r = c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert r.status_code == 200

    rows = c.get("/api/v1/archive", headers=h).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == bid
    assert row["title"] == "数据采集模块"
    assert row["current_published_version"] == "1.0.0"
    assert row["archived_at"] is not None
    assert row["document_id"] == env["document_id"]
    assert row["document_title"] == "经营日报"
    assert row["domain_name"] == "运营"
    assert row["project_name"] == "测试项目"


# ---------- GET /api/v1/activity ----------


def test_activity_recent_first_and_actor_prefix_filter(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)  # human audits: publish (+ derived document publish)
    c.get("/api/v1/index", headers=a)  # agent audit: pull
    c.post(f"/api/v1/blocks/{bid}/ack", json={"version": "1.0.0"}, headers=a)

    r = c.get("/api/v1/activity", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 3
    assert [row["id"] for row in rows] == sorted((row["id"] for row in rows), reverse=True)
    assert {"actor", "action", "target", "detail", "created_at"} <= rows[0].keys()
    actions = {row["action"] for row in rows}
    assert "publish" in actions and "pull" in actions and "ack" in actions

    agent_rows = c.get("/api/v1/activity",
                       params={"actor_prefix": "agent"}, headers=h).json()
    assert agent_rows
    assert all(row["actor"].startswith("agent") for row in agent_rows)
    assert {row["action"] for row in agent_rows} == {"pull", "ack"}

    limited = c.get("/api/v1/activity", params={"limit": 1}, headers=h).json()
    assert len(limited) == 1
    assert limited[0]["id"] == rows[0]["id"]  # limit 截取的是最新的
