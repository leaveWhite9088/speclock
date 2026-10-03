"""Rules delta 提案（proposed_rule_ops）：提交校验、resolve 应用、提案 diff 端点、
发布留痕（applied_ops）。"""

from __future__ import annotations

import copy

from tests.conftest import APIS_V1, RULES_V1, publish_v1

RULE_NEW = {"name": "退款口径", "detail": "退款订单按退款完成时间回冲当月销售额"}

RULES_V2 = RULES_V1 + [
    {"name": "订单口径", "detail": "仅统计支付成功订单，取消订单不计入"},
]


def _put_rules(env, rules):
    r = env["client"].put(
        f"/api/v1/blocks/{env['block_id']}", json={"rules": rules}, headers=env["human"]
    )
    assert r.status_code == 200, r.text


def _submit_rule_ops(env, ops, **overrides):
    body = {
        "block_id": env["block_id"],
        "description": "规则口径需要修正",
        "suggestion": "按 ops 修改业务规则",
        "proposed_rule_ops": ops,
    }
    body.update(overrides)
    return env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])


def _upsert_modified():
    entry = copy.deepcopy(RULES_V1[0])
    entry["detail"] = "支付成功订单金额合计（不含退款、不含积分抵扣部分）"
    return {"op": "upsert", "name": entry["name"], "entry": entry}


def _approve(env, pid):
    return env["client"].post(
        f"/api/v1/proposals/{pid}/resolve",
        json={"action": "approve"},
        headers=env["human"],
    )


def _rules(env):
    return env["client"].get(
        f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]
    ).json()["rules"]


def _inbox_item(env, pid, status=None):
    url = "/api/v1/proposals" + (f"?status={status}" if status else "")
    inbox = env["client"].get(url, headers=env["human"]).json()
    return next(p for p in inbox if p["id"] == pid)


# ---------- 提交与校验 ----------


def test_rule_ops_submit_201_bypasses_empty_check(env):
    """rule_ops 非空 = 有载荷：无需 note_only 即可提交（空载荷 422 不触发）。"""
    publish_v1(env["client"], env["human"], env["block_id"])

    r = _submit_rule_ops(env, [_upsert_modified()])
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    p = env["client"].get(f"/api/v1/proposals/{pid}", headers=env["agent"]).json()
    assert p["proposed_rule_ops"][0]["op"] == "upsert"
    assert p["proposed_rule_ops"][0]["name"] == "销售额口径"
    assert p["note_only"] is False


def test_empty_payload_still_422(env):
    """所有载荷（含 rule_ops）全空且未 note_only：仍 422。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    body = {
        "block_id": env["block_id"],
        "description": "只说问题不带修改",
        "suggestion": "建议人工看看",
    }
    r = env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])
    assert r.status_code == 422
    assert "note_only" in r.json()["detail"]


def test_rule_op_upsert_requires_entry_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_rule_ops(env, [{"op": "upsert", "name": "销售额口径", "entry": None}])
    assert r.status_code == 422


def test_rule_op_entry_name_mismatch_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    op = _upsert_modified()
    op["entry"]["name"] = "别的规则名"
    r = _submit_rule_ops(env, [op])
    assert r.status_code == 422


def test_rule_op_delete_rejects_entry_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_rule_ops(
        env,
        [{"op": "delete", "name": "销售额口径", "entry": copy.deepcopy(RULES_V1[0])}],
    )
    assert r.status_code == 422


def test_rule_op_entry_invalid_422(env):
    """entry 复用 validate_rules 校验：detail 为空 422。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    r = _submit_rule_ops(
        env, [{"op": "upsert", "name": "新规则", "entry": {"name": "新规则", "detail": "  "}}]
    )
    assert r.status_code == 422


# ---------- resolve 应用 ----------


def test_rule_ops_resolve_applies_to_rules(env):
    """upsert 命中原位替换、未命中追加末尾、delete 命中删除；其他规则不动。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    _put_rules(env, RULES_V2)
    publish_v1(c, h, bid)

    pid = _submit_rule_ops(
        env,
        [
            _upsert_modified(),
            {"op": "delete", "name": "订单口径", "entry": None},
            {"op": "upsert", "name": RULE_NEW["name"], "entry": RULE_NEW},
        ],
    ).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 200, r.text

    rules = _rules(env)
    assert [r_["name"] for r_ in rules] == ["销售额口径", "退款口径"]
    assert rules[0]["detail"] == "支付成功订单金额合计（不含退款、不含积分抵扣部分）"
    assert rules[1]["detail"] == RULE_NEW["detail"]


def test_rule_ops_delete_miss_409(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])

    pid = _submit_rule_ops(
        env, [{"op": "delete", "name": "不存在的规则", "entry": None}]
    ).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 409, r.text
    assert "不存在的规则" in r.json()["detail"]

    p = c.get(f"/api/v1/proposals/{pid}", headers=env["agent"]).json()
    assert p["status"] == "submitted"
    assert [r_["name"] for r_ in _rules(env)] == ["销售额口径"]


def test_inbox_rule_ops_enriched(env):
    """收件箱输出带 current_entry / kind / detail_diff（modified 才有 diff）。"""
    publish_v1(env["client"], env["human"], env["block_id"])

    unchanged = {"op": "upsert", "name": "销售额口径", "entry": copy.deepcopy(RULES_V1[0])}
    pid = _submit_rule_ops(
        env,
        [
            _upsert_modified(),
            unchanged,
            {"op": "upsert", "name": RULE_NEW["name"], "entry": RULE_NEW},
        ],
    ).json()["id"]

    ops = _inbox_item(env, pid)["proposed_rule_ops"]
    by_name = {op["name"]: op for op in ops}

    mod = by_name["销售额口径"]
    # 列表里同名 upsert 两条都 enrich；取 modified 的那条
    mod = next(op for op in ops if op["name"] == "销售额口径" and op["kind"] == "modified")
    assert mod["current_entry"]["detail"] == RULES_V1[0]["detail"]
    assert mod["detail_diff"]
    assert "-支付成功订单金额合计（不含退款）" in mod["detail_diff"]

    same = next(op for op in ops if op["name"] == "销售额口径" and op["kind"] == "unchanged")
    assert same["detail_diff"] is None

    added = by_name["退款口径"]
    assert added["kind"] == "added"
    assert added["current_entry"] is None
    assert added["detail_diff"] is None


def test_inbox_content_diff_echoed(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    pid = _submit_rule_ops(
        env,
        [_upsert_modified()],
        proposed_content_md="# 数据采集模块\n\n每日 06:30 汇总前一日经营数据并校验完整性。",
    ).json()["id"]
    p = _inbox_item(env, pid)
    assert p["content_diff"]
    assert "+每日 06:30" in p["content_diff"]


# ---------- 提案 diff 端点 ----------


def _submit_full(env, **overrides):
    entry = copy.deepcopy(APIS_V1[0])
    entry["response"].append(
        {"name": "extra_note", "type": "string", "required": False, "description": "运营备注"}
    )
    body = {
        "block_id": env["block_id"],
        "description": "综合修改提案",
        "suggestion": "正文 + API + 规则一起改",
        "proposed_content_md": "# 数据采集模块\n\n每日 06:30 汇总前一日经营数据并校验完整性。",
        "proposed_api_ops": [{"op": "upsert", "api": entry["api"], "entry": entry}],
        "proposed_rule_ops": [
            _upsert_modified(),
            {"op": "upsert", "name": RULE_NEW["name"], "entry": RULE_NEW},
        ],
    }
    body.update(overrides)
    return env["client"].post("/api/v1/proposals", json=body, headers=env["agent"])


def test_proposal_diff_endpoint(env):
    c, a, h = env["client"], env["agent"], env["human"]
    publish_v1(c, h, env["block_id"])

    pid = _submit_full(env).json()["id"]

    r = c.get(f"/api/v1/proposals/{pid}/diff", headers=a)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["proposal_id"] == pid
    assert d["base_version"] == "1.0.0"
    assert d["base_is_recorded"] is True

    assert "+每日 06:30" in d["content_diff"]

    api_op = d["api_changes"][0]
    assert api_op["op"] == "upsert"
    assert api_op["current_entry"]["api"] == "GET /api/daily-report"
    assert any("extra_note" in m for m in api_op["changes"]["contract"]["added"])

    by_name = {op["name"]: op for op in d["rule_changes"]}
    assert by_name["销售额口径"]["kind"] == "modified"
    assert by_name["销售额口径"]["detail_diff"]
    assert by_name["退款口径"]["kind"] == "added"

    # human key 同样可读
    r = c.get(f"/api/v1/proposals/{pid}/diff", headers=h)
    assert r.status_code == 200, r.text


def test_proposal_diff_requires_key(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    pid = _submit_full(env).json()["id"]
    assert env["client"].get(f"/api/v1/proposals/{pid}/diff").status_code == 401


def test_proposal_diff_base_fallback_after_void(env):
    """base_version 快照被作废：回退当前已发布版本作参照，并标注非原始 base。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)

    pid = _submit_full(env).json()["id"]  # 基于 1.0.0

    # 人工发布 1.0.1（仅改正文），再作废 1.0.0
    r = c.put(f"/api/v1/blocks/{bid}",
              json={"content_md": "# 数据采集模块\n\n每日 06:00 汇总前一日经营数据并归档。"},
              headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "v1.0.1", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/blocks/{bid}/versions/1.0.0/void", headers=h)
    assert r.status_code == 200, r.text

    d = c.get(f"/api/v1/proposals/{pid}/diff", headers=a).json()
    assert d["base_version"] == "1.0.1"
    assert d["base_is_recorded"] is False
    assert d["api_changes"][0]["current_entry"] is not None  # 参照 1.0.1 快照


def test_proposal_diff_base_unavailable_empty_baseline(env):
    """base 与当前版本快照全部不可用：按空基线计算，不报错、不外泄草稿。"""
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)

    pid = _submit_full(env).json()["id"]  # 基于 1.0.0
    r = c.post(f"/api/v1/blocks/{bid}/versions/1.0.0/void", headers=h)
    assert r.status_code == 200, r.text  # 全部作废 → 无可用快照

    d = c.get(f"/api/v1/proposals/{pid}/diff", headers=a).json()
    assert d["base_version"] is None
    assert d["base_is_recorded"] is False
    # 空基线：API 全部视为新增，规则 upsert 均为 added，正文 diff 相对空串
    assert d["api_changes"][0]["current_entry"] is None
    assert {op["kind"] for op in d["rule_changes"]} == {"added"}
    assert d["content_diff"]


# ---------- 发布留痕（applied_ops） ----------


def _version_entry(env, version):
    versions = env["client"].get(
        f"/api/v1/blocks/{env['block_id']}/versions", headers=env["human"]
    ).json()
    return next(v for v in versions if v["version"] == version)


def test_applied_ops_recorded_on_proposal_publish(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])

    pid = _submit_full(env).json()["id"]
    r = _approve(env, pid)
    assert r.status_code == 200, r.text
    version = r.json()["published_version"]

    v = _version_entry(env, version)
    ops = v["applied_ops"]
    assert ops["proposal_id"] == pid
    assert ops["content_md_replaced"] is True
    assert ops["apis"] == [{"op": "upsert", "api": "GET /api/daily-report"}]
    assert ops["rules"] == [
        {"op": "upsert", "name": "销售额口径"},
        {"op": "upsert", "name": "退款口径"},
    ]

    # 版本详情同样可见；非提案发布的 1.0.0 无 ops
    detail = c.get(
        f"/api/v1/blocks/{env['block_id']}/versions/{version}", headers=h
    ).json()
    assert detail["applied_ops"]["proposal_id"] == pid
    assert _version_entry(env, "1.0.0")["applied_ops"] == {}

