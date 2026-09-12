"""归档/恢复派生文档版本（MINOR）+ 归档管理页 + 彻底删除。"""

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


def test_archive_page_renders_rows_and_actions(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    body = c.get(f"/ui/archive?key={h['X-API-Key']}").text
    assert "归档管理" in body
    assert "数据采集模块" in body
    assert "@1.0.0" in body
    assert "恢复" in body
    assert "彻底删除" in body
    assert "purgeBlock" in body and "不可恢复" in body
    # 恢复后列表为空
    c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert "没有已归档的模块" in c.get(f"/ui/archive?key={h['X-API-Key']}").text


def test_tree_hides_archived_blocks(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    c.delete(f"/api/v1/blocks/{bid}", headers=h)
    body = c.get(f"/ui?key={h['X-API-Key']}").text
    # 归档模块不再出现在文档树；恢复/删除只在归档管理页操作
    assert "数据采集模块" not in body
    assert "restoreBlock" not in body
    # 恢复后重新出现
    c.post(f"/api/v1/blocks/{bid}/restore", headers=h)
    assert "数据采集模块" in c.get(f"/ui?key={h['X-API-Key']}").text
