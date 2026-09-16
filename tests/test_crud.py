"""CRUD for Domain / Document / Block + archive semantics.

删除语义：
- 草稿态模块 / 空文档 / 空大业务：直接删除；
- 已发布模块：删除 = 归档（agent 404、index 排除、下一文档版本 manifest 移除），可恢复；
- 文档/大业务删除：其下有已发布模块时 409。
"""

from __future__ import annotations

from tests.conftest import APIS_V1, APIS_V2_MINOR, create_module, publish_v1


# ---------- 模块 CRUD ----------

def test_draft_block_is_hard_deleted(env):
    c, h = env["client"], env["human"]
    bid = create_module(c, h, env["document_id"], "临时草稿模块")
    r = c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert c.get(f"/api/v1/blocks/{bid}/draft", headers=h).status_code == 404


def test_published_block_delete_means_archive(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    r = c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    # agent 读不到、index 排除
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 404
    assert c.get("/api/v1/index", headers=a).json() == []
    # 历史版本保留：human 仍可查版本列表
    versions = c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()
    assert [v["version"] for v in versions] == ["1.0.0"]


def test_archived_block_removed_from_next_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    publish_v1(c, h, bid)   # doc 1.0.0
    publish_v1(c, h, bid2)  # doc 1.1.0
    # 归档模块 1，再给模块 2 发一个新版本
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    c.put(f"/api/v1/blocks/{bid2}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid2}/publish",
           json={"change_note": "加字段", "fastTrack": True}, headers=h)
    r = c.get(f"/api/v1/documents/{did}", headers=a)
    manifest = {m["block_id"]: m["version"] for m in r.json()["manifest"]}
    assert manifest == {bid2: "1.1.0"}  # 归档模块不再出现在 manifest


def test_restore_archived_block(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 404
    r = c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "published"
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["version"] == "1.0.0"
    # 已发布模块不能 restore
    assert c.post(f"/api/v1/blocks/{bid}/restore", headers=h).status_code == 409


# ---------- 文档 CRUD ----------

def test_document_rename(env):
    c, h, did = env["client"], env["human"], env["document_id"]
    r = c.put(f"/api/v1/documents/{did}", json={"name": "经营日报 v2"}, headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "经营日报 v2"


def test_document_delete_blocked_by_published_module(env):
    c, h, did = env["client"], env["human"], env["document_id"]
    publish_v1(c, h, env["block_id"])
    r = c.delete(f"/api/v1/documents/{did}", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["published_blocks"]
    # 归档模块后即可删除
    c.delete(f"/api/v1/blocks/{env['block_id']}", headers=h)
    r = c.delete(f"/api/v1/documents/{did}", headers=h)
    assert r.status_code == 200


def test_empty_document_deletable(env):
    c, h = env["client"], env["human"]
    r = c.post("/api/v1/documents",
               json={"domain_id": env["domain_id"], "title": "空文档"}, headers=h)
    did = r.json()["id"]
    assert c.delete(f"/api/v1/documents/{did}", headers=h).status_code == 200


# ---------- 大业务 CRUD ----------

def test_domain_create_rename_delete(env):
    c, h, pid = env["client"], env["human"], env["project_id"]
    r = c.post("/api/v1/domains", json={"project_id": pid, "name": "采购"}, headers=h)
    assert r.status_code == 201
    did = r.json()["id"]
    r = c.put(f"/api/v1/domains/{did}", json={"name": "采购部"}, headers=h)
    assert r.json()["name"] == "采购部"
    # 空大业务可直接删除
    assert c.delete(f"/api/v1/domains/{did}", headers=h).status_code == 200


def test_domain_delete_blocked_by_published_module(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    r = c.delete(f"/api/v1/domains/{env['domain_id']}", headers=h)
    assert r.status_code == 409


def test_full_create_chain_visible_to_agent(env):
    """新建大业务 → 文档 → 模块 → 发布 → agent 可读。"""
    c, h, a = env["client"], env["human"], env["agent"]
    dm = c.post("/api/v1/domains",
                json={"project_id": env["project_id"], "name": "商品"}, headers=h).json()
    doc = c.post("/api/v1/documents",
                 json={"domain_id": dm["id"], "title": "商品主档"}, headers=h).json()
    blk = c.post("/api/v1/blocks",
                 json={"document_id": doc["id"], "title": "商品查询模块",
                       "content_md": "# 商品查询模块\n\n商品主档的查询业务背景与流程叙述。",
                       "rules": [{"name": "商品状态口径", "detail": "仅上架商品可被前台查询"}],
                       "apis": APIS_V1}, headers=h).json()
    r = c.post(f"/api/v1/blocks/{blk['id']}/publish",
               json={"change_note": "首发", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.0.0"
    assert c.get(f"/api/v1/blocks/{blk['id']}", headers=a).status_code == 200
    docs = c.get("/api/v1/documents", headers=a).json()
    assert any(d["document_id"] == doc["id"] for d in docs)
