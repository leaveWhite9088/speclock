"""发布语义（经由 Commit）：模块 semver、结构化 API 校验、没有确认闸门、草稿不可见、
delta 随版本落库、dryRun 预览。"""

from __future__ import annotations

from tests.conftest import (
    APIS_EMPTY_FIELD_NAME,
    APIS_INVALID_API_NAME,
    APIS_INVALID_TYPE,
    APIS_FIELD_REMOVED,
    APIS_V2_BREAKING,
    APIS_V2_MINOR,
    change_block,
    commit,
    open_cr,
    publish_v1,
)


def test_first_publish_is_1_0_0(env):
    r = publish_v1(env["client"], env["human"], env["block_id"])
    assert r["version"] == "1.0.0"
    assert r["capability_version"] == "1.0.0"
    assert r["delta"]["added"]  # everything is new on first publish
    assert r["level"] == "initial"


def test_added_response_field_bumps_minor(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = change_block(env, env["block_id"], apis=APIS_V2_MINOR, note="加字段")
    assert out["version"] == "1.1.0"
    assert out["level"] == "minor"
    assert any("extra_note" in a for a in out["delta"]["added"])
    assert out["capability_version"] == "1.1.0"


def test_type_change_publishes_directly_as_major(env):
    """没有破坏性确认闸门：类型变更直接发布，标签 MAJOR、版本 2.0.0。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    out = change_block(env, env["block_id"], apis=APIS_V2_BREAKING)
    assert (out["version"], out["level"]) == ("2.0.0", "major")
    assert any("sales" in a for a in out["delta"]["modified"])
    assert "breaking" not in out["raw"] and "affected" not in out["raw"]


def test_removed_field_publishes_directly_as_major(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = change_block(env, env["block_id"], apis=APIS_FIELD_REMOVED)
    assert out["level"] == "major"
    assert any("orders" in a for a in out["delta"]["removed"])


def test_structured_validation_blocks_commit(env):
    """结构化校验：坏类型 / 无法解析的 API 名 / 空字段名 都不能写入。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    for bad in (APIS_INVALID_TYPE, APIS_INVALID_API_NAME, APIS_EMPTY_FIELD_NAME):
        r = change_block(env, env["block_id"], expect=422, apis=bad)
        assert r.status_code == 422, r.text
    # 全部失败的 Commit 都回滚了：版本数不变
    assert len(env["client"].get(
        f"/api/v1/blocks/{env['block_id']}/versions", headers=env["human"]).json()) == 1


def test_invalid_apis_cannot_be_created(env):
    cr_id = open_cr(env)
    r = commit(env, cr_id, [{
        "op": "create_block", "capability": env["capability_id"], "title": "x",
        "content_md": "# x\n\n足够长的业务背景与流程叙述文字。",
        "rules": [{"name": "r", "detail": "d"}], "acceptance": [{"name": "a", "detail": "d"}],
        "apis": APIS_INVALID_TYPE}])
    assert r.status_code == 422


def test_publish_generates_openapi_yaml(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"])
    body = r.json()
    assert "openapi: 3.0.3" in body["openapi_yaml"]
    assert "/api/daily-report" in body["openapi_yaml"]
    # agent 同时拿到结构化 apis（真相源）
    assert body["apis"][0]["api"] == "GET /api/daily-report"
    assert body["apis"][0]["response"][0]["name"] == "sales"


def test_draft_invisible_to_agent(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    # module exists only as a draft
    r = c.get(f"/api/v1/blocks/{bid}", headers=a)
    assert r.status_code == 404
    r = c.get("/api/v1/index", headers=a)
    assert r.status_code == 200
    assert r.json() == []
    # after publish it becomes visible
    publish_v1(c, h, bid)
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).status_code == 200


def test_delta_stored_on_version(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    change_block(env, env["block_id"], apis=APIS_V2_MINOR)
    r = env["client"].get(f"/api/v1/blocks/{env['block_id']}@1.1.0", headers=env["agent"])
    assert r.status_code == 200
    delta = r.json()["delta"]
    assert any("extra_note" in a for a in delta["added"])
    assert delta["removed"] == []


# ---------- dryRun 预览 ----------


def _versions(env):
    return env["client"].get(
        f"/api/v1/blocks/{env['block_id']}/versions", headers=env["human"]).json()


def test_dryrun_does_not_persist(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = open_cr(env)
    before = _versions(env)
    r = commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "apis": APIS_V2_MINOR}],
               dry_run=True)
    assert r.status_code == 200, r.text
    assert len(_versions(env)) == len(before)  # 不落库
    # 当前版本不变，agent 读到的还是旧版
    assert env["client"].get(
        f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).json()["version"] == "1.0.0"


def test_dryrun_preview_content(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env),
               [{"op": "update_block", "id": env["block_id"], "apis": APIS_V2_MINOR}], dry_run=True)
    out = r.json()
    b = out["blocks"][0]
    assert b["version"] == "1.1.0"  # 预测将发布的版本号
    assert b["level"] == "minor"
    assert any("extra_note" in a for a in b["delta"]["added"])
    assert out["capability_versions"][0]["version"] == "1.1.0"  # 预测派生小业务版本


def test_major_dryrun_then_commit(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = open_cr(env)
    ops = [{"op": "update_block", "id": env["block_id"], "apis": APIS_V2_BREAKING}]
    b = commit(env, cr_id, ops, dry_run=True).json()["blocks"][0]
    assert (b["version"], b["level"]) == ("2.0.0", "major")
    # dryRun 不落库；之后真正提交得到同样的版本与标签
    assert len(_versions(env)) == 1
    b = commit(env, cr_id, ops).json()["blocks"][0]
    assert (b["version"], b["level"]) == ("2.0.0", "major")
