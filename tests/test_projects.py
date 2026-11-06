"""项目管理 + 文档隔离：项目 CRUD、key 项目绑定与跨项目访问隔离。"""

from __future__ import annotations

from speclock.db import SessionLocal
from speclock.models import Business, Capability

from .conftest import commit, create_module, make_key, open_cr, publish_v1


def _make_project_with_published_block(env, project_name, block_title):
    """新建项目 → 大业务 → 小业务 → 模块，并发布模块。返回 (project_id, block_id, capability_id)。
    结构直接落库（Commit 路径另有测试），这里只关心隔离。"""
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/projects", json={"name": project_name}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    db = SessionLocal()
    business = Business(project_id=pid, name="默认域")
    db.add(business)
    db.flush()
    cap = Capability(business_id=business.id, title="文档")
    db.add(cap)
    db.commit()
    doc_id = cap.id
    db.close()
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

    # 初始 human key 绑定在「测试项目」上：只看得到自己的项目
    assert [p["name"] for p in c.get("/api/v1/projects", headers=h).json()] == ["测试项目"]

    r = c.delete(f"/api/v1/projects/{pid}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True

    assert c.put("/api/v1/projects/9999", json={"name": "x"}, headers=h).status_code == 404
    assert c.delete("/api/v1/projects/9999", headers=h).status_code == 404


def test_delete_project_with_published_block_rejected(env):
    """项目下仍有已发布模块 → 409；归档后方可删除，绑定该项目的 key 被一并删除。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    boss = make_key(env, "admin", project_bound=False)  # 全局管理员兜底，不会被一并删掉
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=boss)
    assert r.status_code == 409

    r = commit(env, open_cr(env), [{"op": "archive_block", "id": env["block_id"]}])
    assert r.status_code == 200
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=boss)
    assert r.status_code == 200 and r.json()["deleted_keys"] >= 2  # 初始 human + agent（+ 需求 Agent key）
    assert c.get("/api/v1/projects", headers=boss).json() == []
    # 项目的审核单也一并删了
    assert c.get("/api/v1/change-requests", headers=boss).json() == []


def test_delete_project_guard_last_admin_key(env):
    """删除项目会连带删除绑定的最后一把管理员 key 时拒绝。"""
    c, h = env["client"], env["human"]
    r = c.delete(f"/api/v1/projects/{env['project_id']}", headers=h)
    assert r.status_code == 409 and "管理员" in r.json()["detail"]
    # 建一把全局管理员 key 后，项目即可删除
    make_key(env, "admin", project_bound=False)
    assert c.delete(f"/api/v1/projects/{env['project_id']}", headers=h).status_code == 200


def test_create_key_with_project(env):
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/keys",
               json={"role": "executor-agent", "label": "scoped", "project_id": env["project_id"]},
               headers=h)
    assert r.status_code == 201 and r.json()["project_id"] == env["project_id"]
    # 不存在的项目 → 404
    r = c.post("/api/v1/keys", json={"role": "executor-agent", "project_id": 9999}, headers=h)
    assert r.status_code == 404


def test_scoped_agent_key_isolation(env):
    """绑定项目 B 的 agent key：/index 与 /capabilities 只见项目 B；
    跨项目的 block / diff / capability / work 一律 404。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])  # 项目 A（env 默认项目）发布一个模块
    pid_b, bid_b, doc_b = _make_project_with_published_block(env, "项目B", "B项目模块")

    r = c.post("/api/v1/keys",
               json={"role": "executor-agent", "label": "B-agent", "project_id": pid_b}, headers=h)
    assert r.status_code == 201
    scoped = {"X-API-Key": r.json()["key"]}

    # 索引与小业务列表只含项目 B
    index = c.get("/api/v1/index", headers=scoped).json()
    titles = [b["title"] for d in index for doc in d["capabilities"] for b in doc["blocks"]]
    assert titles == ["B项目模块"]
    docs = c.get("/api/v1/capabilities", headers=scoped).json()
    assert [d["capability_id"] for d in docs] == [doc_b]

    # 本项目可读
    assert c.get(f"/api/v1/blocks/{bid_b}", headers=scoped).status_code == 200
    assert c.get(f"/api/v1/capabilities/{doc_b}", headers=scoped).status_code == 200
    own_work = c.get("/api/v1/work", headers=scoped).json()
    assert [w["block_id"] for w in own_work] == [bid_b]  # 待办也只含本项目
    assert c.post(f"/api/v1/work/{own_work[0]['id']}/claim", headers=scoped).status_code == 200

    # 跨项目一律 404
    a_id, a_doc = env["block_id"], env["capability_id"]
    assert c.get(f"/api/v1/blocks/{a_id}", headers=scoped).status_code == 404
    assert c.get(f"/api/v1/blocks/{a_id}/diff", headers=scoped).status_code == 404
    assert c.get(f"/api/v1/capabilities/{a_doc}", headers=scoped).status_code == 404
    a_work = c.get("/api/v1/work", params={"block_id": a_id}, headers=h).json()[0]["id"]
    assert c.get(f"/api/v1/work/{a_work}", headers=scoped).status_code == 404
    assert c.post(f"/api/v1/work/{a_work}/claim", headers=scoped).status_code == 404


def test_global_agent_key_sees_all_projects(env):
    """不绑定项目的 agent key（project_id=None）保持全局可见。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    _make_project_with_published_block(env, "项目B", "B项目模块")

    r = c.post("/api/v1/keys", json={"role": "executor-agent", "label": "global"}, headers=h)
    assert r.status_code == 201 and r.json()["project_id"] is None
    glob = {"X-API-Key": r.json()["key"]}

    index = c.get("/api/v1/index", headers=glob).json()
    titles = {b["title"] for d in index for doc in d["capabilities"] for b in doc["blocks"]}
    assert titles == {"数据采集模块", "B项目模块"}
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=glob).status_code == 200
