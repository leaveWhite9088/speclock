"""删除模块 / 小业务 / 大业务 / 项目：人类专属权限，已发布的要先归档，须附人同意的原话，写进审计。"""

from __future__ import annotations

import json

import pytest

from speclock_core import AuditLog, Block, Business, Capability, SessionLocal
from speclock_mcp import server as mcp_server
from tests.conftest import commit, open_cr, publish_v1
from tests.test_projects import _make_project_with_published_block

WORDS = "好，把它删了"


def _archive(env, block_id):
    cr = open_cr(env)
    r = commit(env, cr, [{"op": "archive_block", "id": block_id}], covers=["AC-1"])
    assert r.status_code == 200, r.text


def _delete(env, path, headers=None, **params):
    return env["client"].delete(f"/api/v1/{path}", params={"via": "natural_language", "evidence": WORDS, **params},
                                headers=headers or env["human"])


def test_published_modules_must_be_archived_first(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    for path in (f"blocks/{env['block_id']}", f"capabilities/{env['capability_id']}", f"businesses/{env['business_id']}"):
        r = _delete(env, path)
        assert r.status_code == 409 and r.json()["code"] == "published_blocks_exist", path
        assert r.json()["detail"]["published_blocks"][0]["id"] == env["block_id"]
    assert env["client"].delete(f"/api/v1/projects/{env['project_id']}", headers=env["human"]).status_code == 409


def test_delete_block_after_archiving_it(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    _archive(env, env["block_id"])
    r = _delete(env, f"blocks/{env['block_id']}")
    assert r.status_code == 200 and r.json() == {"id": env["block_id"], "deleted": True}
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["human"]).status_code == 404
    assert c.get("/api/v1/work", headers=env["human"]).json() == []  # 它的执行记录一并没了
    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "delete", AuditLog.target == f"block:{env['block_id']}").one()
        assert json.loads(row.detail_json)["evidence"] == WORDS and row.project_id == env["project_id"]
    finally:
        db.close()


def test_delete_capability_and_business_cascade(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    _archive(env, env["block_id"])
    assert _delete(env, f"capabilities/{env['capability_id']}").status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Capability, env["capability_id"]) is None and db.get(Block, env["block_id"]) is None
        assert db.get(Business, env["business_id"]) is not None
    finally:
        db.close()
    assert _delete(env, f"businesses/{env['business_id']}").status_code == 200
    assert _delete(env, f"businesses/{env['business_id']}").status_code == 404


def test_evidence_is_required_when_deleting_on_the_humans_behalf(env):
    r = env["client"].delete(f"/api/v1/blocks/{env['block_id']}", params={"via": "natural_language"}, headers=env["human"])
    assert r.status_code == 422 and "evidence" in r.json()["detail"]


def test_only_those_with_spec_delete_can_delete(env):
    c = env["client"]
    for headers in (env["agent"], ):
        assert _delete(env, f"blocks/{env['block_id']}", headers=headers).status_code == 403
    rev = c.post("/api/v1/keys", json={"role": "reviewer", "label": "审核人"}, headers=env["human"]).json()["key"]
    assert _delete(env, f"blocks/{env['block_id']}", headers={"X-API-Key": rev}).status_code == 403


def test_project_admin_deletes_only_inside_its_own_project(env):
    c = env["client"]
    other, other_block, other_cap = _make_project_with_published_block(env, "项目B", "B模块")
    pa = {"X-API-Key": c.post("/api/v1/keys", json={"role": "project-admin", "project_id": env["project_id"]},
                              headers=env["human"]).json()["key"]}
    assert _delete(env, f"blocks/{other_block}", headers=pa).status_code == 404
    assert _delete(env, f"capabilities/{other_cap}", headers=pa).status_code == 404
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=pa)  # 删项目是超级管理员的事
    assert r.status_code == 403
    assert _delete(env, f"blocks/{env['block_id']}", headers=pa).status_code == 200  # 本项目的草稿模块


def test_delete_project_records_the_words(env):
    pid, _, _ = _make_project_with_published_block(env, "要删的项目", "模块")
    assert _delete(env, f"projects/{pid}").status_code == 409  # 里面还有已发布模块


@pytest.fixture()
def mcp(env, monkeypatch):
    c = env["client"]
    monkeypatch.setattr(mcp_server.httpx, "request", lambda method, url, headers=None, timeout=None, **kw:
                        c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw))
    monkeypatch.setattr(mcp_server, "AGENT_KEY", env["human"]["X-API-Key"])
    return lambda raw: json.loads(raw)


def test_mcp_delete_tools(env, mcp):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = mcp(mcp_server.delete_block(env["block_id"], WORDS))
    assert out["status"] == 409 and out["body"]["code"] == "published_blocks_exist"
    _archive(env, env["block_id"])
    assert mcp(mcp_server.delete_block(env["block_id"], WORDS))["body"] == {"id": env["block_id"], "deleted": True}
    assert mcp(mcp_server.delete_capability(env["capability_id"], WORDS))["status"] == 200
    assert mcp(mcp_server.delete_business(env["business_id"], WORDS))["status"] == 200
    pid, bid, _ = _make_project_with_published_block(env, "要删的项目", "模块")
    assert mcp(mcp_server.delete_project(pid, WORDS))["body"]["code"] == "published_blocks_exist"
    mcp_server.AGENT_KEY = env["agent"]["X-API-Key"]
    assert mcp(mcp_server.delete_project(pid, WORDS))["status"] == 403
