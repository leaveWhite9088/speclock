"""Nested (recursive) API field structure: validation, diff, breaking rules,
OpenAPI generation, save/read round-trip."""

from __future__ import annotations

import copy

from tests.conftest import publish_v1

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


def test_nested_roundtrip_save_and_read(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V1}, headers=h)
    assert r.status_code == 200, r.text
    draft = c.get(f"/api/v1/blocks/{bid}/draft", headers=h).json()
    rule = draft["apis"][0]["request"][0]
    assert rule["type"] == "object"
    assert rule["children"][2]["children"][0]["name"] == "region"
    publish_v1(c, h, bid)
    body = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert body["apis"][0]["request"][0]["children"][2]["children"][0]["name"] == "region"


def test_children_rejected_under_scalar_type(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}",
              json={"apis": NESTED_INVALID_CHILDREN_ON_SCALAR}, headers=h)
    assert r.status_code == 422
    assert "children" in r.json()["detail"]


def test_empty_children_on_scalar_tolerated(env):
    """回归：GET 读出的标量字段都带空 children: []，原样 PUT 回必须 200。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    apis = c.get(f"/api/v1/blocks/{bid}", headers=a).json()["apis"]
    # 确认读出的标量确实带空 children
    assert apis[0]["response"][0]["children"] == []
    r = c.put(f"/api/v1/blocks/{bid}", json={"apis": apis}, headers=h)
    assert r.status_code == 200, r.text
    # 且读回结构不变
    apis2 = c.get(f"/api/v1/blocks/{bid}/draft", headers=h).json()["apis"]
    assert apis2 == apis


def test_removing_optional_field_is_not_breaking(env):
    """规则细化：删可选字段（required=false）非破坏性，可走 fastTrack。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V1}, headers=h)
    publish_v1(c, h, bid)
    v2 = copy.deepcopy(NESTED_V1)
    del v2[0]["request"][0]["children"][2]  # 删除可选的 rule.scope（required=false）
    c.put(f"/api/v1/blocks/{bid}", json={"apis": v2}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "删可选字段", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["breaking"] is False
    assert any("rule.scope" in a for a in body["delta"]["removed"])
    assert body["version"] == "1.0.1"  # 仅删除无新增 -> PATCH


def test_nested_field_added_is_minor_with_dotted_path(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    c, h, bid = env["client"], env["human"], env["block_id"]
    # v1 用嵌套结构重新发布一版
    c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V1}, headers=h)
    c.post(f"/api/v1/blocks/{bid}/publish",
           json={"change_note": "换成规则接口", "confirm": True}, headers=h)
    # v2 在 rule.scope 下加 store_name 子字段
    c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V2_MINOR}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "scope 加门店维度", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["breaking"] is False
    assert any(
        "request:POST /api/daily-report/anomaly-rules:rule.scope.store_name" in a
        for a in body["delta"]["added"]
    )


def test_nested_type_change_is_breaking(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V1}, headers=h)
    publish_v1(c, h, bid)
    c.put(f"/api/v1/blocks/{bid}", json={"apis": NESTED_V2_BREAKING}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "threshold 改类型", "fastTrack": True}, headers=h)
    assert r.status_code == 409
    affected = r.json()["detail"]["affected"]
    assert any("rule.threshold" in a and a.startswith("request:") for a in affected)
    assert any("rule.threshold: number required -> string required" in a for a in affected)


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
