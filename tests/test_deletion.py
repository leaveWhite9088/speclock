"""删除模块 / 小业务 / 大业务 / 项目：必须有人批准过的业务变更单授权（单子里点名要删的东西）；
已发布的要先归档；写进审计。"""

from __future__ import annotations

import json

import pytest

from speclock_core import AuditLog, Block, Business, Capability, SessionLocal
from speclock_mcp import server as mcp_server
from tests.conftest import commit, cr_body, make_key, open_cr, publish_v1
from tests.test_projects import _make_project_with_published_block

BLOCK, CAP, BIZ = "数据采集模块", "经营日报", "运营"


def _delete_cr(env, name, approve=True, **over):
    """开一张点名要删 name 的业务变更单（默认让人批准了）。"""
    return open_cr(env, approve=approve, title=f"删除 {name}", intent=f"{name} 不再需要了，从库里删掉", **over)


def _archive(env, block_id):
    cr = open_cr(env)
    r = commit(env, cr, [{"op": "archive_block", "id": block_id}], covers=["AC-1"])
    assert r.status_code == 200, r.text


def _delete(env, path, cr_id, headers=None):
    return env["client"].delete(f"/api/v1/{path}", params={"cr_id": cr_id}, headers=headers or env["human"])


def _code(r):
    return r.json()["code"]


def test_a_deletion_needs_an_approved_change_request_that_names_it(env):
    c = env["client"]
    path = f"blocks/{env['block_id']}"
    r = c.delete(f"/api/v1/{path}", headers=env["human"])  # 没带 cr_id
    assert r.status_code == 422
    r = _delete(env, path, 9999)  # 不存在的单子
    assert r.status_code == 409 and _code(r) == "delete_needs_approval"
    pending = _delete_cr(env, BLOCK, approve=False)  # 还没批准
    r = _delete(env, path, pending)
    assert r.status_code == 409 and _code(r) == "delete_needs_approval" and "pending_review" in r.json()["detail"]
    unrelated = open_cr(env, title="调整口径", intent="别的事")  # 批准了，但没点名这个模块
    r = _delete(env, path, unrelated)
    assert r.status_code == 409 and _code(r) == "delete_needs_approval" and BLOCK in r.json()["detail"]
    internal = open_cr(env, approve=False, kind="internal", kind_reason="改名", title=f"删除 {BLOCK}", intent=BLOCK)
    assert _delete(env, path, internal).status_code == 409  # 内部整理单没有人批准，不能授权删除


def test_the_request_must_belong_to_the_same_project(env):
    other, other_block, _ = _make_project_with_published_block(env, "项目B", "B模块")
    cr = _delete_cr(env, "B模块")  # 开在项目 A（点名了 B 的模块，也不行）
    r = _delete(env, f"blocks/{other_block}", cr, headers=make_key(env, "admin", project_bound=False))
    assert r.status_code == 409 and _code(r) == "delete_needs_approval"


def test_published_modules_must_be_archived_first(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    for path, name in ((f"blocks/{env['block_id']}", BLOCK), (f"capabilities/{env['capability_id']}", CAP),
                       (f"businesses/{env['business_id']}", BIZ)):
        r = _delete(env, path, _delete_cr(env, name))
        assert r.status_code == 409 and _code(r) == "published_blocks_exist", path
        assert r.json()["detail"]["published_blocks"][0]["id"] == env["block_id"]


def test_delete_block_after_archiving_it(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    _archive(env, env["block_id"])
    cr = _delete_cr(env, BLOCK)
    r = _delete(env, f"blocks/{env['block_id']}", cr)
    assert r.status_code == 200 and r.json() == {"id": env["block_id"], "deleted": True}
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["human"]).status_code == 404
    assert c.get("/api/v1/work", headers=env["human"]).json() == []  # 它的执行记录一并没了
    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "delete", AuditLog.target == f"block:{env['block_id']}").one()
        detail = json.loads(row.detail_json)
        assert detail["cr_id"] == cr and detail["cr_title"] == f"删除 {BLOCK}" and row.project_id == env["project_id"]
    finally:
        db.close()


def test_delete_capability_and_business_cascade(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    _archive(env, env["block_id"])
    assert _delete(env, f"capabilities/{env['capability_id']}", _delete_cr(env, CAP)).status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Capability, env["capability_id"]) is None and db.get(Block, env["block_id"]) is None
        assert db.get(Business, env["business_id"]) is not None
    finally:
        db.close()
    cr = _delete_cr(env, BIZ)
    assert _delete(env, f"businesses/{env['business_id']}", cr).status_code == 200
    assert _delete(env, f"businesses/{env['business_id']}", cr).status_code == 404


def test_delete_a_whole_project_with_an_approved_request_of_that_project(env):
    c = env["client"]
    root = make_key(env, "admin", project_bound=False)
    glob = make_key(env, "requirements-agent", project_bound=False)  # 升级前就有的全局 key，能给任何项目开单
    pid = c.post("/api/v1/projects", json={"name": "要删的项目"}, headers=root).json()["id"]
    body = cr_body(project_id=pid, title="删除 要删的项目", intent="项目作废")
    cr = c.post("/api/v1/change-requests", json=body, headers=glob).json()["id"]
    c.post(f"/api/v1/change-requests/{cr}/submit", headers=glob)
    assert _delete(env, f"projects/{pid}", cr, headers=root).status_code == 409  # 还没批准
    h = c.get(f"/api/v1/change-requests/{cr}", headers=root).json()["content_hash"]
    assert c.post(f"/api/v1/change-requests/{cr}/approve", json={"content_hash": h}, headers=root).status_code == 200
    assert _delete(env, f"projects/{env['project_id']}", cr, headers=root).status_code == 409  # 单子是另一个项目的
    r = _delete(env, f"projects/{pid}", cr, headers=root)
    assert r.status_code == 200 and r.json()["deleted"]
    assert all(p["id"] != pid for p in c.get("/api/v1/projects", headers=root).json())


def test_only_those_with_spec_delete_can_delete(env):
    c = env["client"]
    cr = _delete_cr(env, BLOCK)
    assert _delete(env, f"blocks/{env['block_id']}", cr, headers=env["agent"]).status_code == 403
    rev = c.post("/api/v1/keys", json={"role": "reviewer", "label": "审核人", "project_id": env["project_id"]},
                 headers=env["human"]).json()["key"]
    assert _delete(env, f"blocks/{env['block_id']}", cr, headers={"X-API-Key": rev}).status_code == 403


def test_project_admin_deletes_only_inside_its_own_project(env):
    c = env["client"]
    other, other_block, other_cap = _make_project_with_published_block(env, "项目B", "B模块")
    pa = {"X-API-Key": c.post("/api/v1/keys", json={"role": "project-admin", "project_id": env["project_id"]},
                              headers=env["human"]).json()["key"]}
    cr = _delete_cr(env, BLOCK)
    assert _delete(env, f"blocks/{other_block}", cr, headers=pa).status_code == 404
    assert _delete(env, f"capabilities/{other_cap}", cr, headers=pa).status_code == 404
    assert _delete(env, f"projects/{env['project_id']}", cr, headers=pa).status_code == 403  # 删项目是超级管理员的事
    assert _delete(env, f"blocks/{env['block_id']}", cr, headers=pa).status_code == 200  # 本项目的草稿模块


@pytest.fixture()
def mcp(env, monkeypatch):
    c = env["client"]
    monkeypatch.setattr(mcp_server.httpx, "request", lambda method, url, headers=None, timeout=None, **kw:
                        c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw))
    monkeypatch.setattr(mcp_server, "AGENT_KEY", env["human"]["X-API-Key"])
    return lambda raw: json.loads(raw)


def test_mcp_delete_tools(env, mcp):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = mcp(mcp_server.delete_block(env["block_id"], _delete_cr(env, BLOCK)))
    assert out["status"] == 409 and out["body"]["code"] == "published_blocks_exist"
    out = mcp(mcp_server.delete_block(env["block_id"], 9999))
    assert out["status"] == 409 and out["body"]["code"] == "delete_needs_approval"
    _archive(env, env["block_id"])
    assert mcp(mcp_server.delete_block(env["block_id"], _delete_cr(env, BLOCK)))["body"] == {"id": env["block_id"], "deleted": True}
    assert mcp(mcp_server.delete_capability(env["capability_id"], _delete_cr(env, CAP)))["status"] == 200
    assert mcp(mcp_server.delete_business(env["business_id"], _delete_cr(env, BIZ)))["status"] == 200
    mcp_server.AGENT_KEY = env["agent"]["X-API-Key"]
    assert mcp(mcp_server.delete_project(env["project_id"], 1))["status"] == 403
