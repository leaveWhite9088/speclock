"""项目管理 + 文档隔离：项目 CRUD、agent key 项目绑定与跨项目访问隔离。"""

from __future__ import annotations

from .conftest import create_module, publish_v1


def _make_project_with_published_block(env, project_name, block_title):
    """新建项目 → 大业务 → 文档 → 模块，并发布模块。返回 (project_id, block_id, document_id)。"""
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/projects", json={"name": project_name}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    r = c.post("/api/v1/domains", json={"project_id": pid, "name": "默认域"}, headers=h)
    assert r.status_code == 201
    did = r.json()["id"]
    r = c.post("/api/v1/documents", json={"domain_id": did, "title": "文档"}, headers=h)
    assert r.status_code == 201
    doc_id = r.json()["id"]
    bid = create_module(c, h, doc_id, block_title)
    publish_v1(c, h, bid)
    return pid, bid, doc_id


def test_project_crud(env):
    c, h = env["client"], env["human"]
    projects = c.get("/api/v1/projects", headers=h).json()
    assert [p["name"] for p in projects] == ["测试项目"]

    r = c.post("/api/v1/projects", json={"name": "项目B"}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]

    r = c.put(f"/api/v1/projects/{pid}", json={"name": "项目B2"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "项目B2"

    r = c.delete(f"/api/v1/projects/{pid}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert [p["name"] for p in c.get("/api/v1/projects", headers=h).json()] == ["测试项目"]

    assert c.put("/api/v1/projects/9999", json={"name": "x"}, headers=h).status_code == 404
    assert c.delete("/api/v1/projects/9999", headers=h).status_code == 404


def test_delete_project_with_published_block_rejected(env):
    """项目下仍有已发布模块 → 409；归档后方可删除。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=h)
    assert r.status_code == 409

    # 归档模块后即可删除，绑定该项目的 key 被一并删除
    assert c.delete(f"/api/v1/blocks/{env['block_id']}", headers=h).status_code == 200
    # 初始 human key 绑在本项目上且是唯一一把：先建一把全局 human key 兜底
    r2 = c.post("/api/v1/keys", json={"prefix": "human", "label": "backup"}, headers=h)
    assert r2.status_code == 201
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=h)
    assert r.status_code == 200 and r.json()["deleted_keys"] == 2  # 初始 human + agent
    # 文档树里不再有该项目
    assert c.get("/api/v1/projects", headers={"X-API-Key": r2.json()["key"]}).json() == []


def test_delete_project_guard_last_human_key(env):
    """删除项目会连带删除绑定的最后一把 human key 时拒绝。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    assert c.delete(f"/api/v1/blocks/{env['block_id']}", headers=h).status_code == 200
    # 先删掉未绑定的……初始两把 key 都绑在唯一项目上：直接删项目应被 409 保护
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=h)
    assert r.status_code == 409
    # 建一把全局 human key 后，项目即可删除
    r2 = c.post("/api/v1/keys", json={"prefix": "human", "label": "backup"}, headers=h)
    assert r2.status_code == 201
    assert c.delete(f"/api/v1/projects/{env['project_id']}", headers=h).status_code == 200


def test_create_key_with_project(env):
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/keys",
               json={"prefix": "agent", "label": "scoped", "project_id": env["project_id"]},
               headers=h)
    assert r.status_code == 201 and r.json()["project_id"] == env["project_id"]
    # 不存在的项目 → 404
    r = c.post("/api/v1/keys", json={"prefix": "agent", "project_id": 9999}, headers=h)
    assert r.status_code == 404


def test_scoped_agent_key_isolation(env):
    """绑定项目 B 的 agent key：/index 与 /documents 只见项目 B；
    跨项目的 block/diff/document/ack/proposal 一律 404。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])  # 项目 A（env 默认项目）发布一个模块
    pid_b, bid_b, doc_b = _make_project_with_published_block(env, "项目B", "B项目模块")

    r = c.post("/api/v1/keys",
               json={"prefix": "agent", "label": "B-agent", "project_id": pid_b}, headers=h)
    assert r.status_code == 201
    scoped = {"X-API-Key": r.json()["key"]}

    # 索引与文档列表只含项目 B
    index = c.get("/api/v1/index", headers=scoped).json()
    titles = [b["title"] for d in index for doc in d["documents"] for b in doc["blocks"]]
    assert titles == ["B项目模块"]
    docs = c.get("/api/v1/documents", headers=scoped).json()
    assert [d["document_id"] for d in docs] == [doc_b]

    # 本项目可读
    assert c.get(f"/api/v1/blocks/{bid_b}", headers=scoped).status_code == 200
    assert c.get(f"/api/v1/documents/{doc_b}", headers=scoped).status_code == 200
    assert c.post(f"/api/v1/blocks/{bid_b}/ack",
                  json={"version": "1.0.0"}, headers=scoped).status_code == 201
    r = c.post("/api/v1/proposals",
               json={"block_id": bid_b, "description": "d", "suggestion": "s"},
               headers=scoped)
    assert r.status_code == 201
    assert c.get(f"/api/v1/proposals/{r.json()['id']}", headers=scoped).status_code == 200

    # 跨项目一律 404
    a_id, a_doc = env["block_id"], env["document_id"]
    assert c.get(f"/api/v1/blocks/{a_id}", headers=scoped).status_code == 404
    assert c.get(f"/api/v1/blocks/{a_id}/diff", headers=scoped).status_code == 404
    assert c.get(f"/api/v1/documents/{a_doc}", headers=scoped).status_code == 404
    assert c.post(f"/api/v1/blocks/{a_id}/ack",
                  json={"version": "1.0.0"}, headers=scoped).status_code == 404
    assert c.post("/api/v1/proposals",
                  json={"block_id": a_id, "description": "d", "suggestion": "s"},
                  headers=scoped).status_code == 404


def test_global_agent_key_sees_all_projects(env):
    """不绑定项目的 agent key（project_id=None）保持全局可见，向后兼容。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    _make_project_with_published_block(env, "项目B", "B项目模块")

    r = c.post("/api/v1/keys", json={"prefix": "agent", "label": "global"}, headers=h)
    assert r.status_code == 201 and r.json()["project_id"] is None
    glob = {"X-API-Key": r.json()["key"]}

    index = c.get("/api/v1/index", headers=glob).json()
    titles = {b["title"] for d in index for doc in d["documents"] for b in doc["blocks"]}
    assert titles == {"数据采集模块", "B项目模块"}
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=glob).status_code == 200
