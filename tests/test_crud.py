"""结构语义：大业务 / 小业务 / 模块只能经由 Commit 创建与修改；没有硬删除接口
（模块下线 = 归档，可恢复；只有删除整个项目才会硬删）。"""

from __future__ import annotations

from tests.conftest import APIS_V1, ACCEPTANCE_V1, RULES_V1, commit, open_cr, publish_v1

BG = "# 商品查询模块\n\n商品主档的查询业务背景与流程叙述。"


def _ok(env, ops, **kw):
    r = commit(env, open_cr(env), ops, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_business_create_and_rename(env):
    c = env["client"]
    out = _ok(env, [{"op": "create_business", "ref": "b", "name": "采购"}])
    bid = out["created"]["$b"]["id"]
    _ok(env, [{"op": "update_business", "id": bid, "name": "采购部"}])
    names = [b["name"] for b in c.get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"]]
    assert names == ["运营", "采购部"]
    # 空的大业务对 agent 不可见（没有任何已发布模块）
    assert c.get("/api/v1/index", headers=env["agent"]).json() == []


def test_full_create_chain_visible_to_agent(env):
    """新建大业务 → 小业务 → 模块（一个 Commit）→ agent 可读，首版 1.0.0。"""
    c, a = env["client"], env["agent"]
    out = _ok(env, [
        {"op": "create_business", "ref": "b", "name": "商品"},
        {"op": "create_capability", "ref": "c", "business": "$b", "title": "商品主档"},
        {"op": "create_block", "ref": "k", "capability": "$c", "title": "商品查询模块",
         "content_md": BG,
         "rules": [{"name": "商品状态口径", "detail": "仅上架商品可被前台查询"}],
         "acceptance": [{"name": "查询正确", "detail": "下架商品不会出现在前台查询结果里"}],
         "apis": APIS_V1},
    ])
    block = out["blocks"][0]
    assert block["version"] == "1.0.0"
    assert c.get(f"/api/v1/blocks/{block['block_id']}", headers=a).status_code == 200
    docs = c.get("/api/v1/capabilities", headers=a).json()
    assert any(d["capability_id"] == out["created"]["$c"]["id"] for d in docs)


def test_published_block_archive_keeps_history(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    _ok(env, [{"op": "archive_block", "id": bid}])
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 404
    assert c.get("/api/v1/index", headers=a).json() == []
    versions = c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()
    assert [v["version"] for v in versions] == ["1.0.0"]


def test_project_delete_blocked_by_published_module_until_archived(env):
    c, h = env["client"], env["human"]
    other = c.post("/api/v1/projects", json={"name": "另一个项目"}, headers=h).json()["id"]
    assert other
    publish_v1(c, h, env["block_id"])
    keep = c.post("/api/v1/keys", json={"role": "admin"}, headers=h).json()  # 全局管理员兜底
    cr = open_cr(env, title="删除 测试项目", intent="项目作废")
    r = c.delete(f"/api/v1/projects/{env['project_id']}", params={"cr_id": cr}, headers={"X-API-Key": keep["key"]})
    assert r.status_code == 409 and r.json()["detail"]["published_blocks"]
    _ok(env, [{"op": "archive_block", "id": env["block_id"]}])
    r = c.delete(f"/api/v1/projects/{env['project_id']}", params={"cr_id": cr}, headers={"X-API-Key": keep["key"]})
    assert r.status_code == 200


def test_new_block_without_apis_is_fine(env):
    """API 可以为空（纯业务规则的模块）：背景 + 规则 + 验收条件齐全即可发布。"""
    out = _ok(env, [{"op": "create_block", "capability": env["capability_id"], "title": "纯规则模块",
                     "content_md": BG, "rules": RULES_V1, "acceptance": ACCEPTANCE_V1}])
    assert out["blocks"][0]["version"] == "1.0.0"
