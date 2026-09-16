"""Multi-API modules: delta/diff edge cases across API list entries."""

from __future__ import annotations

import copy

from tests.conftest import APIS_V1, publish_v1

THREE_APIS = [
    {
        "name": "查询每项采集状态",
        "api": "GET /api/daily-report/collect-status",
        "desc": "运营日报页调用，逐项查看采集进度；只读",
        "request": [{"name": "date", "type": "string", "required": True,
                     "description": "查询日期", "children": []}],
        "response": [
            {"name": "items", "type": "array", "required": True,
             "description": "逐项状态", "children": [
                 {"name": "item_name", "type": "string", "required": True,
                  "description": "", "children": []},
                 {"name": "status", "type": "string", "required": True,
                  "description": "", "children": []}]},
        ],
    },
    {
        "name": "查询采集项",
        "api": "GET /api/daily-report/collect-items",
        "desc": "运营日报页调用，列出当日应采集项目；只读",
        "request": [{"name": "date", "type": "string", "required": True,
                     "description": "", "children": []}],
        "response": [{"name": "items", "type": "array", "required": True,
                      "description": "", "children": [
                          {"name": "item_id", "type": "string", "required": True,
                           "description": "", "children": []}]}],
    },
    {
        "name": "重新采集特定项",
        "api": "POST /api/daily-report/recollect",
        "desc": "运营在日报页对失败项触发重采；幂等，重复提交返回同一任务",
        "request": [{"name": "item_ids", "type": "array", "required": True,
                     "description": "", "children": [
                         {"name": "item_id", "type": "string", "required": True,
                          "description": "", "children": []}]}],
        "response": [{"name": "accepted", "type": "boolean", "required": True,
                      "description": "", "children": []}],
    },
]


def _set_apis_and_publish(env, apis, note, **kw):
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"apis": apis}, headers=h)
    assert r.status_code == 200, r.text
    body = {"change_note": note}
    body.update(kw)
    return c.post(f"/api/v1/blocks/{bid}/publish", json=body, headers=h)


def test_multi_api_module_publish_and_read(env):
    r = _set_apis_and_publish(env, THREE_APIS, "三 API 首发", fastTrack=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.0.0"
    # 三个 API 条目都进入 delta
    added_apis = [a for a in body["delta"]["added"] if a.startswith("api:")]
    assert len(added_apis) == 3
    # agent 读到完整 3 API 结构
    out = env["client"].get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).json()
    assert [a["name"] for a in out["apis"]] == ["查询每项采集状态", "查询采集项", "重新采集特定项"]


def test_adding_one_api_is_minor(env):
    _set_apis_and_publish(env, THREE_APIS, "首发", fastTrack=True)
    four = copy.deepcopy(THREE_APIS)
    four.append({"name": "查询采集日志", "api": "GET /api/daily-report/collect-logs",
                 "desc": "排查用，拉取采集任务日志；只读", "request": [], "response": []})
    r = _set_apis_and_publish(env, four, "加第四个 API", fastTrack=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.1.0"
    assert body["breaking"] is False
    assert any(a.startswith("api:GET /api/daily-report/collect-logs") for a in body["delta"]["added"])


def test_removing_one_api_is_breaking(env):
    _set_apis_and_publish(env, THREE_APIS, "首发", fastTrack=True)
    two = copy.deepcopy(THREE_APIS[:2])  # 删掉「重新采集特定项」
    r = _set_apis_and_publish(env, two, "删 API", fastTrack=True)
    assert r.status_code == 409
    affected = r.json()["detail"]["affected"]
    assert any(a.startswith("api:POST /api/daily-report/recollect") for a in affected)
    # 该 API 的请求/响应字段也一并列入受影响清单
    assert any("recollect:item_ids" in a for a in affected)
    # confirm 后可发布
    r = _set_apis_and_publish(env, two, "删 API", confirm=True)
    assert r.status_code == 200
    assert r.json()["version"] == "2.0.0"


def test_field_change_scoped_to_its_api(env):
    """多个 API 时，改其中一个 API 的字段，delta 只涉及该 API 的路径。"""
    _set_apis_and_publish(env, THREE_APIS, "首发", fastTrack=True)
    modified = copy.deepcopy(THREE_APIS)
    modified[2]["response"].append({"name": "task_id", "type": "string",
                                    "required": False, "description": "", "children": []})
    r = _set_apis_and_publish(env, modified, "recollect 响应加 task_id", fastTrack=True)
    assert r.status_code == 200, r.text
    added = r.json()["delta"]["added"]
    assert added == ["response:POST /api/daily-report/recollect:task_id: string"]


def test_same_path_different_methods_are_distinct_apis(env):
    """同一路径不同方法应视为不同 API，互不影响。"""
    apis = [
        {"name": "查", "api": "GET /api/x", "desc": "查询 x；只读", "request": [], "response": []},
        {"name": "增", "api": "POST /api/x", "desc": "新建 x；幂等", "request": [], "response": []},
    ]
    _set_apis_and_publish(env, apis, "首发", fastTrack=True)
    rest = copy.deepcopy(apis)
    rest[0]["response"].append({"name": "total", "type": "integer",
                                "required": False, "description": "", "children": []})
    r = _set_apis_and_publish(env, rest, "GET 响应加 total", fastTrack=True)
    assert r.status_code == 200
    assert r.json()["delta"]["added"] == ["response:GET /api/x:total: integer"]
