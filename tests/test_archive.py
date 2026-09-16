"""归档/恢复派生文档版本（MINOR）+ 归档列表 API + 彻底删除。"""

from __future__ import annotations

from tests.conftest import APIS_V1, create_module, publish_v1


def _manifest(client, agent, doc_id, version=None):
    ref = f"{doc_id}@{version}" if version else str(doc_id)
    return {
        m["block_id"]: m["version"]
        for m in client.get(f"/api/v1/documents/{ref}", headers=agent).json()["manifest"]
    }


def test_archive_derives_document_version_and_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    publish_v1(c, h, bid)   # doc 1.0.0
    publish_v1(c, h, bid2)  # doc 1.1.0
    before = c.get(f"/api/v1/documents/{did}", headers=a).json()
    assert before["version"] == "1.1.0"

    r = c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert r.status_code == 200
    assert r.json()["document_version"] == "1.2.0"  # 归档立即派生 MINOR

    after = c.get(f"/api/v1/documents/{did}", headers=a).json()
    assert after["version"] == "1.2.0"
    assert _manifest(c, a, did) == {bid2: "1.0.0"}  # 归档模块不再出现

    # pin 旧文档版本仍能看到历史快照（含归档前模块）——语义自洽
    assert _manifest(c, a, did, "1.1.0") == {bid: "1.0.0", bid2: "1.0.0"}
    # 归档时间已记录
    draft = c.get(f"/api/v1/blocks/{bid}/draft", headers=h).json()
    assert draft["status"] == "archived"


def test_restore_derives_document_version_and_returns_to_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    assert _manifest(c, a, did) == {}

    r = c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert r.status_code == 200
    assert r.json()["document_version"] == "1.2.0"  # 1.0.0 → 归档 1.1.0 → 恢复 1.2.0
    assert _manifest(c, a, did) == {bid: "1.0.0"}  # 模块回到 manifest


def test_purge_only_for_archived_and_hard_deletes(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    # 已发布模块不能彻底删除
    assert c.delete(f"/api/v1/blocks/{bid}/purge", headers=h).status_code == 409
    c.delete(f"/api/v1/blocks/{bid}", headers=h)  # 先归档
    r = c.delete(f"/api/v1/blocks/{bid}/purge", headers=h)
    assert r.status_code == 200
    assert r.json()["purged"] is True
    # 模块与版本历史都不在了
    assert c.get(f"/api/v1/blocks/{bid}/draft", headers=h).status_code == 404
    assert c.get(f"/api/v1/blocks/{bid}/versions", headers=h).status_code == 404


def test_archive_api_lists_archived_blocks(env):
    """对应 SPA 归档管理页的数据源：GET /api/v1/archive。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    rows = c.get("/api/v1/archive", headers=h).json()
    row = next(r for r in rows if r["id"] == bid)
    assert row["title"] == "数据采集模块"
    assert row["current_published_version"] == "1.0.0"
    assert row["document_title"] == "经营日报"
    assert row["archived_at"] is not None
    # 恢复后列表为空
    c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert c.get("/api/v1/archive", headers=h).json() == []


def test_tree_marks_archived_blocks(env):
    """GET /api/v1/tree 返回全部状态的模块，归档模块以 status 标记，由 SPA 过滤/展示。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)

    def block_row():
        tree = c.get("/api/v1/tree", headers=h).json()
        blocks = tree[0]["domains"][0]["documents"][0]["blocks"]
        return next(b for b in blocks if b["id"] == bid)

    assert block_row()["status"] == "archived"
    c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert block_row()["status"] == "published"
