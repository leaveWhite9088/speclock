"""搜索：规格（模块 / 规则 / 验收条件 / API）与审核单；项目隔离、权限、片段、归档不可见。"""

from __future__ import annotations

from speclock.permissions import get_role  # noqa: F401  (确保角色已就位)
from tests.conftest import (
    APIS_V1,
    change_block,
    commit,
    make_key,
    open_cr,
    publish_v1,
)


def _search(env, q, headers=None, **params):
    r = env["client"].get("/api/v1/search", params={"q": q, **params}, headers=headers or env["human"])
    assert r.status_code == 200, r.text
    return r.json()


def _types(result):
    return [h["type"] for h in result["hits"]]


def test_finds_rules_acceptance_and_api_with_location_and_snippet(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    rule = _search(env, "销售额口径")
    assert "rule" in _types(rule)
    h = next(h for h in rule["hits"] if h["type"] == "rule")
    assert (h["block_id"], h["item_id"], h["version"]) == (env["block_id"], "R-1", "1.0.0")
    assert "销售额口径" in h["snippet"] and h["business"] == "运营" and h["capability_title"] == "经营日报"

    ac = next(h for h in _search(env, "采集完成")["hits"] if h["type"] == "acceptance")
    assert ac["item_id"] == "AC-1"

    api = next(h for h in _search(env, "daily-report")["hits"] if h["type"] == "api")
    assert api["item_id"] == "GET /api/daily-report" and "拉取日报主表" in api["title"]


def test_finds_api_field_names_and_descriptions(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    by_field = _search(env, "orders")  # 响应字段名
    assert any(h["type"] == "api" for h in by_field["hits"])
    assert any(h["type"] == "api" for h in _search(env, "订单量")["hits"])  # 字段说明


def test_module_hit_once_per_module_and_case_insensitive(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _search(env, "数据采集")
    assert _types(r).count("module") == 1
    assert _search(env, "GET /API/DAILY")["total"] >= 1  # 不区分大小写


def test_search_sees_only_the_current_published_version(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    change_block(env, env["block_id"], rule_ops=[{"op": "upsert", "id": "R-1",
                                                  "entry": {"name": "销售额口径", "detail": "新口径含退款"}}])
    assert _search(env, "支付成功订单金额合计")["hits"] == [] or all(
        "支付成功订单金额合计" not in h["snippet"] for h in _search(env, "支付成功订单金额合计")["hits"]
        if h["type"] == "rule")
    assert any(h["type"] == "rule" and "含退款" in h["snippet"] for h in _search(env, "新口径")["hits"])


def test_unpublished_and_archived_modules_are_not_found(env):
    assert _search(env, "数据采集")["hits"] == []  # 只有草稿
    publish_v1(env["client"], env["human"], env["block_id"])
    cr = open_cr(env)
    commit(env, cr, [{"op": "archive_block", "id": env["block_id"]}], covers=["AC-1"])
    assert not [h for h in _search(env, "数据采集")["hits"] if h["type"] != "cr"]


def test_finds_change_requests_when_allowed(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    open_cr(env, title="调整退款口径", intent="财务要求退款不再计入销售额")
    r = _search(env, "退款")
    cr = next(h for h in r["hits"] if h["type"] == "cr")
    assert cr["title"] == "调整退款口径" and cr["status"] == "approved" and cr["cr_id"]
    # 没有 cr.read 的角色只看到规格命中（审核单不出现）
    scanner = make_key(env, "reviewer")  # reviewer 有 cr.read；用自定义角色验证没有 cr.read 的情况
    assert any(h["type"] == "cr" for h in _search(env, "退款", headers=scanner)["hits"])
    c, h = env["client"], env["human"]
    c.post("/api/v1/roles", headers=h, json={"name": "specreader", "kind": "agent", "permissions": ["spec.read"]})
    plain = make_key(env, "specreader")
    assert not any(x["type"] == "cr" for x in _search(env, "退款", headers=plain)["hits"])


def test_results_are_grouped_by_type_order(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    open_cr(env, title="采集规则调整")
    order = {"module": 0, "rule": 1, "acceptance": 2, "api": 3, "cr": 4}
    types = _types(_search(env, "采集"))
    assert types == sorted(types, key=order.get)


def test_limit_and_truncation(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _search(env, "a", limit=1)
    assert len(r["hits"]) == 1 and r["total"] >= 1
    if r["total"] > 1:
        assert r["truncated"] is True


def test_validation_and_permissions(env):
    c = env["client"]
    assert c.get("/api/v1/search", params={"q": "  "}, headers=env["human"]).status_code == 422
    assert c.get("/api/v1/search", headers=env["human"]).status_code == 422
    assert c.get("/api/v1/search", params={"q": "x"}).status_code == 401
    nobody = c.post("/api/v1/roles", headers=env["human"],
                    json={"name": "nobody", "kind": "agent", "permissions": []})
    assert nobody.status_code == 201
    k = make_key(env, "nobody")
    assert c.get("/api/v1/search", params={"q": "x"}, headers=k).status_code == 403


def test_project_isolation(env):
    from tests.test_projects import _make_project_with_published_block

    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    pid_b, bid_b, _ = _make_project_with_published_block(env, "项目B", "独有的B项目模块")
    scoped = {"X-API-Key": c.post("/api/v1/keys", json={"role": "executor-agent", "project_id": pid_b},
                                  headers=h).json()["key"]}
    assert [x["block_id"] for x in _search(env, "独有的B项目", headers=scoped)["hits"]] == [bid_b]
    # 绑定项目 B 的 key 搜到的命中全部属于项目 B，看不到项目 A 的模块
    seen = {x["block_id"] for x in _search(env, "采集", headers=scoped)["hits"] if "block_id" in x}
    assert env["block_id"] not in seen
    # 管理员可以用 project_id 参数收窄
    assert env["block_id"] not in {x["block_id"] for x in _search(env, "采集", project_id=pid_b)["hits"]}
    assert env["block_id"] in {x["block_id"] for x in _search(env, "采集", project_id=env["project_id"])["hits"]}
