"""Nested (recursive) API field structure: validation, diff, MAJOR-level rules,
OpenAPI generation, save/read round-trip."""

from __future__ import annotations

import copy

from tests.conftest import change_block, publish_v1

NESTED_V1 = [
    {
        "name": "保存异常规则",
        "api": "POST /api/daily-report/anomaly-rules",
        "desc": "运营在规则配置页保存规则；带 rule_id 为修改，幂等",
        "request": [
            {
                "name": "rule",
                "type": "object",
                "required": True,
                "description": "规则对象",
                "children": [
                    {"name": "metric", "type": "string", "required": True,
                     "description": "指标名", "children": []},
                    {"name": "threshold", "type": "number", "required": True,
                     "description": "阈值", "children": []},
                    {"name": "scope", "type": "object", "required": False,
                     "description": "生效范围", "children": [
                         {"name": "region", "type": "string", "required": False,
                          "description": "大区", "children": []},
                     ]},
                ],
            }
        ],
        "response": [
            {"name": "saved", "type": "boolean", "required": True,
             "description": "", "children": []},
        ],
    }
]

NESTED_V2_MINOR = copy.deepcopy(NESTED_V1)
NESTED_V2_MINOR[0]["request"][0]["children"][2]["children"].append(
    {"name": "store_name", "type": "string", "required": False,
     "description": "门店", "children": []}
)

NESTED_V2_BREAKING = copy.deepcopy(NESTED_V1)
NESTED_V2_BREAKING[0]["request"][0]["children"][1]["type"] = "string"  # threshold: number -> string

NESTED_INVALID_CHILDREN_ON_SCALAR = copy.deepcopy(NESTED_V1)
NESTED_INVALID_CHILDREN_ON_SCALAR[0]["request"][0]["children"][0]["children"] = [
    {"name": "x", "type": "string"}
]  # string 字段不允许有 children


def test_nested_roundtrip_write_and_read(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    change_block(env, bid, apis=NESTED_V1)
    body = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    rule = body["apis"][0]["request"][0]
    assert rule["type"] == "object"
    assert rule["children"][2]["children"][0]["name"] == "region"


def test_children_rejected_under_scalar_type(env):
    r = change_block(env, env["block_id"], expect=422, apis=NESTED_INVALID_CHILDREN_ON_SCALAR)
    assert r.status_code == 422
    assert "children" in r.json()["detail"]


def test_empty_children_on_scalar_tolerated(env):
    """回归：GET 读出的标量字段都带空 children: []，原样写回必须被接受。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    apis = c.get(f"/api/v1/blocks/{bid}", headers=a).json()["apis"]
    # 确认读出的标量确实带空 children
    assert apis[0]["response"][0]["children"] == []
    out = change_block(env, bid, apis=apis,
                       content_md="# 数据采集模块\n\n只改背景，API 原样写回，足够二十个字符。")
    assert out["delta"]["added"] == [] and out["delta"]["removed"] == [] and out["delta"]["modified"] == []
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["apis"] == apis  # 读回结构不变


def test_removing_optional_field_is_major(env):
    """任何删除都是 MAJOR，包括可选字段。"""
    bid = env["block_id"]
    change_block(env, bid, apis=NESTED_V1)
    v2 = copy.deepcopy(NESTED_V1)
    del v2[0]["request"][0]["children"][2]  # 删除可选的 rule.scope（required=false）
    body = change_block(env, bid, apis=v2, note="删可选字段")
    assert any("rule.scope" in a for a in body["delta"]["removed"])
    assert (body["version"], body["level"]) == ("2.0.0", "major")


def test_nested_field_added_is_minor_with_dotted_path(env):
    bid = env["block_id"]
    change_block(env, bid, apis=NESTED_V1, note="换成规则接口")
    body = change_block(env, bid, apis=NESTED_V2_MINOR, note="scope 加门店维度")
    assert body["level"] == "minor"
    assert any(
        "request:POST /api/daily-report/anomaly-rules:rule.scope.store_name" in a
        for a in body["delta"]["added"]
    )


def test_nested_type_change_is_major(env):
    bid = env["block_id"]
    change_block(env, bid, apis=NESTED_V1)
    body = change_block(env, bid, apis=NESTED_V2_BREAKING, note="threshold 改类型")
    assert body["level"] == "major"
    modified = body["delta"]["modified"]
    assert any("rule.threshold" in a and a.startswith("request:") for a in modified)
    assert any("rule.threshold: number required -> string required" in a for a in modified)


def test_nested_openapi_generation(env):
    import yaml

    from speclock.diffing import apis_to_openapi

    doc = apis_to_openapi(NESTED_V1)
    schema = doc["paths"]["/api/daily-report/anomaly-rules"]["post"]["requestBody"][
        "content"]["application/json"]["schema"]
    rule = schema["properties"]["rule"]
    assert rule["type"] == "object"
    assert rule["properties"]["threshold"]["type"] == "number"
    assert rule["properties"]["scope"]["properties"]["region"]["type"] == "string"
    assert "scope" not in rule.get("required", [])  # 非必填不进 required
    assert "metric" in rule["required"]
    # 整体仍是合法 YAML 可序列化
    yaml.safe_dump(doc, allow_unicode=True)


def test_nested_array_children_generate_items_schema(env):
    from speclock.diffing import apis_to_openapi

    apis = [{
        "name": "查历史", "api": "GET /api/x/history", "desc": "查历史快照；只读", "request": [],
        "response": [{"name": "rows", "type": "array", "required": True,
                      "description": "", "children": [
                          {"name": "date", "type": "string", "required": True,
                           "description": "", "children": []}]}],
    }]
    doc = apis_to_openapi(apis)
    rows = doc["paths"]["/api/x/history"]["get"]["responses"]["200"]["content"][
        "application/json"]["schema"]["properties"]["rows"]
    assert rows["type"] == "array"
    assert rows["items"]["type"] == "object"
    assert rows["items"]["properties"]["date"]["type"] == "string"
