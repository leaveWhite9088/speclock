"""Delta 提案（proposed_api_ops）：合并语义、stale 检查与校验规则。"""

from __future__ import annotations

import copy

from tests.conftest import APIS_V1, APIS_V2_MINOR, publish_v1

APIS_OTHER = [
    {
        "name": "采集状态查询",
        "api": "GET /api/collect-status",
        "desc": "采集任务看板调用，只读无副作用",
        "request": [],
        "response": [
            {"name": "status", "type": "string", "required": True, "description": "采集状态"},
        ],
    }
]

APIS_TWO = APIS_V1 + APIS_OTHER


def _entry(api, name="导入日报", desc="运营手工补录入口，幂等按日期覆盖"):
    return {
        "name": name,
        "api": api,
        "desc": desc,
        "request": [
            {"name": "date", "type": "string", "required": True, "description": "补录日期"},
        ],
        "response": [
            {"name": "ok", "type": "boolean", "required": True, "description": "是否成功"},
        ],
    }


def _upsert_daily():
    entry = copy.deepcopy(APIS_V1[0])
    entry["response"].append(
        {"name": "extra_note", "type": "string", "required": False, "description": "运营备注"}
    )
    return {"op": "upsert", "api": entry["api"], "entry": entry}


def _submit_ops(env, ops, **overrides):
    body = {
        "block_id": env["block_id"],
        "description": "日报接口需要补充字段",
        "suggestion": "响应体增加 extra_note 字段",
        "proposed_api_ops": ops,
    }
    body.update(overrides)
    return env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])


def _approve(env, pid):
    return env["client"].post(
        f"/api/v1/proposals/{pid}/resolve",
        json={"action": "approve"},
        headers=env["human"],
    )


def _apis(env):
    return env["client"].get(
        f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]
    ).json()["apis"]


def test_delta_upsert_replaces_existing_keeps_others(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    r = _submit_ops(env, [_upsert_daily()])
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    p = c.get(f"/api/v1/proposals/{pid}", headers=env["agent"]).json()
    assert p["base_version"] == "1.0.0"
    assert p["proposed_api_ops"][0]["op"] == "upsert"
    assert p["proposed_apis"] is None

    r = _approve(env, pid)
    assert r.status_code == 200, r.text
    assert r.json()["published_version"] == "1.1.0"

    apis = _apis(env)
    assert [a["api"] for a in apis] == ["GET /api/daily-report", "GET /api/collect-status"]
    daily = apis[0]
    assert any(f["name"] == "extra_note" for f in daily["response"])
    # 未携带的 API 原样保留
    assert apis[1]["response"][0]["name"] == "status"


def test_delta_upsert_appends_when_missing(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    new_api = "POST /api/daily-report/import"
    pid = _submit_ops(
        env, [{"op": "upsert", "api": new_api, "entry": _entry(new_api)}]
    ).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 200, r.text

    apis = _apis(env)
    assert [a["api"] for a in apis] == [
        "GET /api/daily-report",
        "GET /api/collect-status",
        new_api,  # 未命中追加到末尾
    ]


def test_delta_delete_hit(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    pid = _submit_ops(
        env, [{"op": "delete", "api": "GET /api/collect-status", "entry": None}]
    ).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 200, r.text

    assert [a["api"] for a in _apis(env)] == ["GET /api/daily-report"]


def test_delta_delete_miss_409(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    pid = _submit_ops(
        env, [{"op": "delete", "api": "GET /api/nonexistent", "entry": None}]
    ).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 409, r.text
    assert "GET /api/nonexistent" in r.json()["detail"]

    # 草稿未被改动，提案仍待处理
    p = c.get(f"/api/v1/proposals/{pid}", headers=env["agent"]).json()
    assert p["status"] == "submitted"
    assert [a["api"] for a in _apis(env)] == [
        "GET /api/daily-report",
        "GET /api/collect-status",
    ]


def test_delta_stale_conflict_409(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    pid = _submit_ops(env, [_upsert_daily()]).json()["id"]  # 基于 1.0.0

    # 基底之后：human 发布了改动同一 API 的新版本
    publish_v1(c, h, bid, apis=APIS_V2_MINOR + APIS_OTHER)
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["version"] == "1.1.0"

    r = _approve(env, pid)
    assert r.status_code == 409, r.text
    assert "基底版本已过期" in r.json()["detail"]
    assert "GET /api/daily-report" in r.json()["detail"]
    assert c.get(f"/api/v1/proposals/{pid}", headers=a).json()["status"] == "submitted"


def test_delta_stale_but_disjoint_ops_merge(env):
    """基底过期但 ops 只动未变化的 API：正常合并。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    op = _upsert_daily()
    op["api"] = "GET /api/collect-status"
    op["entry"] = copy.deepcopy(APIS_OTHER[0])
    op["entry"]["response"].append(
        {"name": "finished_at", "type": "string", "required": False, "description": "完成时间"}
    )
    pid = _submit_ops(env, [op]).json()["id"]  # 基于 1.0.0

    publish_v1(c, h, bid, apis=APIS_V2_MINOR + APIS_OTHER)  # 只动了 daily-report

    r = _approve(env, pid)
    assert r.status_code == 200, r.text
    apis = _apis(env)
    assert any(f["name"] == "extra_note" for f in apis[0]["response"])
    assert any(f["name"] == "finished_at" for f in apis[1]["response"])


def test_ops_and_full_apis_mutually_exclusive_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_ops(env, [_upsert_daily()], proposed_apis=APIS_TWO)
    assert r.status_code == 422


def test_entry_api_mismatch_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    op = _upsert_daily()
    op["entry"]["api"] = "GET /api/other-path"
    r = _submit_ops(env, [op])
    assert r.status_code == 422


def test_upsert_requires_entry_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_ops(env, [{"op": "upsert", "api": "GET /api/daily-report", "entry": None}])
    assert r.status_code == 422


def test_delete_rejects_entry_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_ops(
        env,
        [{"op": "delete", "api": "GET /api/daily-report", "entry": _entry("GET /api/daily-report")}],
    )
    assert r.status_code == 422


def test_legacy_full_mode_regression(env):
    """旧 proposed_apis 全量替换路径不变，且同样记录 base_version。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    body = {
        "block_id": bid,
        "description": "只保留日报接口",
        "suggestion": "整体替换",
        "proposed_apis": APIS_V2_MINOR,
    }
    r = c.post("/api/v1/proposals", json=body, headers=a)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    p = c.get(f"/api/v1/proposals/{pid}", headers=a).json()
    assert p["base_version"] == "1.0.0"  # 全量模式也记录基底版本
    assert p["proposed_api_ops"] is None

    r = _approve(env, pid)
    assert r.status_code == 200, r.text
    # 整体替换：未携带的 collect-status 被移除（旧语义不变）
    assert [a["api"] for a in _apis(env)] == ["GET /api/daily-report"]


def test_base_version_null_when_unpublished(env):
    """未发布过的模块对 agent 不可见；这里验证首次发布前的提案无从提交，
    以及发布前 base_version 语义由已发布版本号决定（见其他用例的 1.0.0）。"""
    r = _submit_ops(env, [_upsert_daily()])  # block 仍是草稿
    assert r.status_code == 404


def test_admin_inbox_echoes_delta_fields(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)
    pid = _submit_ops(env, [_upsert_daily()]).json()["id"]

    p = next(p for p in c.get("/api/v1/proposals", headers=h).json() if p["id"] == pid)
    assert p["base_version"] == "1.0.0"
    assert p["proposed_apis"] is None
    assert p["proposed_api_ops"][0]["api"] == "GET /api/daily-report"
    assert p["proposed_api_ops"][0]["entry"]["response"][-1]["name"] == "extra_note"


def _inbox_op(env, pid):
    inbox = env["client"].get("/api/v1/proposals", headers=env["human"]).json()
    p = next(p for p in inbox if p["id"] == pid)
    return p["proposed_api_ops"][0]


def test_inbox_op_current_entry_hit_and_changes(env):
    """current_entry 命中当前定义；changes 同时报契约变更（必填标志翻转）
    与文案变更（desc 改动），二者分组区分。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)

    entry = copy.deepcopy(APIS_V1[0])
    entry["desc"] = "改写后的端点语义：日报页与看板双端调用，只读"
    entry["response"][0]["required"] = False  # sales 必填标志翻转（契约变更）
    pid = _submit_ops(
        env, [{"op": "upsert", "api": entry["api"], "entry": entry}]
    ).json()["id"]

    op = _inbox_op(env, pid)
    assert op["current_entry"]["desc"] == APIS_V1[0]["desc"]
    assert op["current_entry"]["response"][0]["required"] is True

    contract = op["changes"]["contract"]
    assert any("sales" in m and "required" in m for m in contract["modified"])
    assert contract["added"] == []
    assert contract["removed"] == []

    text = op["changes"]["text"]
    desc_change = next(c for c in text if c["path"] == "desc")
    assert desc_change["old"] == APIS_V1[0]["desc"]
    assert desc_change["new"] == "改写后的端点语义：日报页与看板双端调用，只读"


def test_inbox_op_field_description_change_is_text(env):
    """字段 description 改动归入文案变更，不出现在契约变更里（flatten 排除文案）。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)

    entry = copy.deepcopy(APIS_V1[0])
    entry["response"][0]["description"] = "销售额（含税口径，改写）"
    pid = _submit_ops(
        env, [{"op": "upsert", "api": entry["api"], "entry": entry}]
    ).json()["id"]

    op = _inbox_op(env, pid)
    assert op["changes"]["contract"] == {"added": [], "modified": [], "removed": []}
    fc = next(c for c in op["changes"]["text"] if c["path"] == "response:sales.description")
    assert fc["old"] == "销售额"
    assert fc["new"] == "销售额（含税口径，改写）"


def test_inbox_op_current_entry_null_for_new_api(env):
    """upsert 未命中：current_entry 为 null（新增 API），契约变更全部为 added。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)

    new_api = "POST /api/daily-report/import"
    pid = _submit_ops(
        env, [{"op": "upsert", "api": new_api, "entry": _entry(new_api)}]
    ).json()["id"]

    op = _inbox_op(env, pid)
    assert op["current_entry"] is None
    assert any(new_api in a for a in op["changes"]["contract"]["added"])
    assert op["changes"]["text"] == []


def test_inbox_delete_op_has_current_entry_no_changes(env):
    """delete op：带将被删除的当前条目，无 changes。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)

    pid = _submit_ops(
        env, [{"op": "delete", "api": "GET /api/collect-status", "entry": None}]
    ).json()["id"]

    op = _inbox_op(env, pid)
    assert op["current_entry"]["api"] == "GET /api/collect-status"
    assert op["current_entry"]["response"][0]["name"] == "status"
    assert op["changes"] is None


def _submit_legacy(env, apis, **overrides):
    body = {
        "block_id": env["block_id"],
        "description": "整体替换 API 列表",
        "suggestion": "按提案列表整体替换",
        "proposed_apis": apis,
    }
    body.update(overrides)
    return env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])


def _inbox_item(env, pid, status=None):
    url = "/api/v1/proposals" + (f"?status={status}" if status else "")
    inbox = env["client"].get(url, headers=env["human"]).json()
    return next(p for p in inbox if p["id"] == pid)


def test_legacy_view_submitted(env):
    """legacy submitted：view 按 API 分拆，upsert 对照当前 draft，
    未携带的条目以显式 delete 出现；proposed_apis 原字段不变。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)

    changed = copy.deepcopy(APIS_V1[0])
    changed["desc"] = "改写后的端点语义（整体替换提案）"
    pid = _submit_legacy(env, [changed]).json()["id"]

    p = _inbox_item(env, pid)
    assert [a["api"] for a in p["proposed_apis"]] == ["GET /api/daily-report"]
    view = p["proposed_apis_view"]
    assert [v["op"] for v in view] == ["upsert", "delete"]

    up = view[0]
    assert up["api"] == "GET /api/daily-report"
    assert up["current_entry"]["desc"] == APIS_V1[0]["desc"]  # 当前 draft
    desc_change = next(c for c in up["changes"]["text"] if c["path"] == "desc")
    assert desc_change["old"] == APIS_V1[0]["desc"]
    assert desc_change["new"] == "改写后的端点语义（整体替换提案）"

    delete = view[1]
    assert delete["api"] == "GET /api/collect-status"  # 隐含删除显式可见
    assert delete["entry"] is None
    assert delete["current_entry"]["response"][0]["name"] == "status"
    assert delete["changes"] is None


def test_legacy_view_published_references_previous_version(env):
    """legacy published：参照系是 published_version 的前一个已发布版本（1.0.0），
    不是当前 draft（批准已把 draft 改成提案内容）。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    changed = copy.deepcopy(APIS_V1[0])
    changed["desc"] = "改写后的端点语义（整体替换提案）"
    pid = _submit_legacy(env, [changed]).json()["id"]

    r = _approve(env, pid)
    assert r.status_code == 200, r.text
    assert r.json()["published_version"] == "2.0.0"  # 删除 collect-status 为破坏性

    p = _inbox_item(env, pid, status="published")
    assert p["base_version"] == "1.0.0"
    view = p["proposed_apis_view"]
    assert [v["op"] for v in view] == ["upsert", "delete"]

    up = view[0]
    # 当前 draft 已是提案内容，current_entry 必须来自 1.0.0 快照（旧 desc）
    assert up["current_entry"]["desc"] == APIS_V1[0]["desc"]
    desc_change = next(c for c in up["changes"]["text"] if c["path"] == "desc")
    assert desc_change["old"] == APIS_V1[0]["desc"]
    assert desc_change["new"] == "改写后的端点语义（整体替换提案）"
    assert view[1]["api"] == "GET /api/collect-status"
    assert view[1]["current_entry"]["api"] == "GET /api/collect-status"

    # agent 视角的已发布版本确认提案内容已生效
    apis = c.get(f"/api/v1/blocks/{bid}", headers=a).json()["apis"]
    assert [e["api"] for e in apis] == ["GET /api/daily-report"]


def test_legacy_view_rejected_uses_current_draft(env):
    """legacy rejected：参照系是当前 draft——拒绝后 draft 继续演进，
    view 跟着最新 draft 走。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)

    changed = copy.deepcopy(APIS_V1[0])
    changed["desc"] = "改写后的端点语义（整体替换提案）"
    pid = _submit_legacy(env, [changed]).json()["id"]
    r = c.post(f"/api/v1/proposals/{pid}/resolve",
               json={"action": "reject", "resolution_note": "不采纳"}, headers=h)
    assert r.status_code == 200, r.text

    # 拒绝后 human 独立演进 draft 并发布（desc 文案改动 → patch）
    human_edit = copy.deepcopy(APIS_TWO)
    human_edit[0]["desc"] = "人工改写的端点语义"
    publish_v1(c, h, bid, apis=human_edit)

    p = _inbox_item(env, pid, status="rejected")
    view = p["proposed_apis_view"]
    up = next(v for v in view if v["op"] == "upsert")
    assert up["current_entry"]["desc"] == "人工改写的端点语义"  # 最新 draft，非 1.0.0
    desc_change = next(c for c in up["changes"]["text"] if c["path"] == "desc")
    assert desc_change["old"] == "人工改写的端点语义"
    assert desc_change["new"] == "改写后的端点语义（整体替换提案）"
    assert any(v["op"] == "delete" and v["api"] == "GET /api/collect-status" for v in view)
