"""归档 / 恢复（经由 Commit）派生小业务版本（MINOR）+ 归档列表 API + 树里的状态标记。"""

from __future__ import annotations

from tests.conftest import APIS_V1, commit, create_module, open_cr, publish_v1


def _manifest(client, agent, doc_id, version=None):
    ref = f"{doc_id}@{version}" if version else str(doc_id)
    return {
        m["block_id"]: m["version"]
        for m in client.get(f"/api/v1/capabilities/{ref}", headers=agent).json()["manifest"]
    }


def _archive(env, bid):
    r = commit(env, open_cr(env), [{"op": "archive_block", "id": bid}])
    assert r.status_code == 200, r.text
    return r.json()


def _restore(env, bid):
    r = commit(env, open_cr(env), [{"op": "restore_block", "id": bid}])
    assert r.status_code == 200, r.text
    return r.json()


def test_archive_derives_capability_version_and_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["capability_id"]
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    publish_v1(c, h, bid)   # doc 1.0.0
    publish_v1(c, h, bid2)  # doc 1.1.0
    before = c.get(f"/api/v1/capabilities/{did}", headers=a).json()
    assert before["version"] == "1.1.0"

    out = _archive(env, bid)
    assert out["capability_versions"][0]["version"] == "1.2.0"  # 归档立即派生 MINOR

    after = c.get(f"/api/v1/capabilities/{did}", headers=a).json()
    assert after["version"] == "1.2.0"
    assert _manifest(c, a, did) == {bid2: "1.0.0"}  # 归档模块不再出现

    # pin 旧小业务版本仍能看到历史快照（含归档前模块）——语义自洽
    assert _manifest(c, a, did, "1.1.0") == {bid: "1.0.0", bid2: "1.0.0"}
    # 历史版本保留：human 仍可查版本列表与快照
    assert [v["version"] for v in c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()] == ["1.0.0"]
    assert c.get(f"/api/v1/blocks/{bid}/versions/1.0.0", headers=h).json()["status"] == "archived"
    # agent 读不到归档模块、index 排除
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 404


def test_archived_block_stays_out_of_next_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["capability_id"]
    bid2 = create_module(c, h, did, "异常数据展示模块", apis=APIS_V1)
    publish_v1(c, h, bid)
    publish_v1(c, h, bid2)
    _archive(env, bid)
    from tests.conftest import APIS_V2_MINOR, change_block

    change_block(env, bid2, apis=APIS_V2_MINOR, note="加字段")
    assert _manifest(c, a, did) == {bid2: "1.1.0"}  # 归档模块不再出现在 manifest


def test_restore_derives_capability_version_and_returns_to_manifest(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["capability_id"]
    publish_v1(c, h, bid)
    _archive(env, bid)
    assert _manifest(c, a, did) == {}

    out = _restore(env, bid)
    assert out["capability_versions"][0]["version"] == "1.2.0"  # 1.0.0 → 归档 1.1.0 → 恢复 1.2.0
    assert _manifest(c, a, did) == {bid: "1.0.0"}  # 模块回到 manifest
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["version"] == "1.0.0"


def test_archive_api_lists_archived_blocks(env):
    """对应 SPA 归档页的数据源：GET /api/v1/archive。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _archive(env, bid)
    rows = c.get("/api/v1/archive", headers=h).json()
    row = next(r for r in rows if r["id"] == bid)
    assert row["title"] == "数据采集模块"
    assert row["current_published_version"] == "1.0.0"
    assert row["capability_title"] == "经营日报"
    assert row["archived_at"] is not None
    # 恢复后列表为空
    _restore(env, bid)
    assert c.get("/api/v1/archive", headers=h).json() == []


def test_tree_marks_archived_blocks(env):
    """GET /api/v1/tree 返回全部状态的模块，归档模块以 status 标记，由 SPA 过滤 / 展示。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _archive(env, bid)

    def block_row():
        tree = c.get("/api/v1/tree", headers=h).json()
        blocks = tree[0]["businesses"][0]["capabilities"][0]["blocks"]
        return next(b for b in blocks if b["id"] == bid)

    assert block_row()["status"] == "archived"
    _restore(env, bid)
    assert block_row()["status"] == "published"
