"""完成标记（completed）：手动 complete/uncomplete、发布自动重置、
index/manifest/get_block 中的完成字段、domain/incomplete 过滤、diff 默认值。"""

from __future__ import annotations

from tests.conftest import APIS_V2_MINOR, create_module, publish_v1


def flatten_blocks(tree):
    return [b for d in tree for doc in d["documents"] for b in doc["blocks"]]


def test_complete_and_uncomplete(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    r = c.post(f"/api/v1/blocks/{bid}/complete", headers=h)
    assert r.status_code == 200
    assert r.json()["completed"] is True
    assert r.json()["completed_version"] == "1.0.0"
    r = c.post(f"/api/v1/blocks/{bid}/uncomplete", headers=h)
    assert r.status_code == 200
    assert r.json()["completed"] is False


def test_complete_requires_published(env):
    r = env["client"].post(f"/api/v1/blocks/{env['block_id']}/complete",
                           headers=env["human"])
    assert r.status_code == 409


def test_publish_resets_completed(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    c.post(f"/api/v1/blocks/{bid}/complete", headers=h)
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    entry = flatten_blocks(c.get("/api/v1/index", headers=env["agent"]).json())[0]
    assert entry["completed"] is False  # 自动重置
    assert entry["completed_version"] == "1.0.0"  # 上次完成版本保留为历史信息
    assert entry["version"] == "1.1.0"


def test_index_carries_completion_fields(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    entry = flatten_blocks(c.get("/api/v1/index", headers=a).json())[0]
    assert entry["completed"] is False
    assert entry["completed_version"] is None
    c.post(f"/api/v1/blocks/{bid}/complete", headers=h)
    entry = flatten_blocks(c.get("/api/v1/index", headers=a).json())[0]
    assert entry["completed"] is True
    assert entry["completed_version"] == "1.0.0"


def test_index_incomplete_filter(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    bid2 = create_module(c, h, did, "异常数据展示模块")
    publish_v1(c, h, bid)
    publish_v1(c, h, bid2)
    c.post(f"/api/v1/blocks/{bid}/complete", headers=h)
    r = c.get("/api/v1/index", params={"incomplete": "true"}, headers=a).json()
    assert [e["block_id"] for e in flatten_blocks(r)] == [bid2]
    # 不过滤时两个都在
    assert len(flatten_blocks(c.get("/api/v1/index", headers=a).json())) == 2


def test_index_domain_filter(env):
    c, h, a = env["client"], env["human"], env["agent"]
    publish_v1(c, h, env["block_id"])
    # 另一个大业务下的模块
    dm = c.post("/api/v1/domains", json={"project_id": env["project_id"], "name": "商品"},
                headers=h).json()
    doc = c.post("/api/v1/documents", json={"domain_id": dm["id"], "title": "商品主档"},
                 headers=h).json()
    blk = c.post("/api/v1/blocks",
                 json={"document_id": doc["id"], "title": "商品查询模块",
                       "content_md": "# 商品查询模块\n\n商品主档的查询业务背景与流程叙述。",
                       "rules": [{"name": "商品状态口径", "detail": "仅上架商品可被前台查询"}]},
                 headers=h).json()
    publish_v1(c, h, blk["id"])

    r = c.get("/api/v1/index", params={"domain": "运营"}, headers=a).json()
    assert [e["block_id"] for e in flatten_blocks(r)] == [env["block_id"]]
    assert c.get("/api/v1/index", params={"domain": "不存在"}, headers=a).json() == []
    # documents 同样支持 domain 过滤
    docs = c.get("/api/v1/documents", params={"domain": "商品"}, headers=a).json()
    assert [d["title"] for d in docs] == ["商品主档"]
    # 组合：domain + incomplete
    c.post(f"/api/v1/blocks/{env['block_id']}/complete", headers=h)
    r = c.get("/api/v1/index", params={"domain": "运营", "incomplete": "true"}, headers=a).json()
    assert r == []


def test_get_block_and_manifest_carry_completion(env):
    c, h, a, bid, did = env["client"], env["human"], env["agent"], env["block_id"], env["document_id"]
    publish_v1(c, h, bid)
    c.post(f"/api/v1/blocks/{bid}/complete", headers=h)
    body = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert body["completed"] is True
    assert body["completed_version"] == "1.0.0"
    doc = c.get(f"/api/v1/documents/{did}", headers=a).json()
    entry = doc["manifest"][0]
    assert entry["completed"] is True
    assert entry["completed_version"] == "1.0.0"


def test_diff_defaults_to_last_two_versions(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    r = c.get(f"/api/v1/blocks/{bid}/diff", headers=a)  # 不带 from/to
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "1.0.0" and body["to"] == "1.1.0"
    assert any("extra_note" in x for x in body["delta"]["added"])


def test_diff_single_version_friendly_message(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"/api/v1/blocks/{env['block_id']}/diff", headers=env["agent"])
    assert r.status_code == 200
    assert "暂无可对比" in r.json()["message"]
