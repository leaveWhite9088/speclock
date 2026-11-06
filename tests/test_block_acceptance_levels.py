"""Block 重构：验收条件、规则 / 验收条件的稳定 id、机械版本级别标签、派生 Deprecated 状态。
（写入一律经由审核单下的 Commit：用 change_block 辅助函数。）"""

from __future__ import annotations

import copy

import pytest

from speclock import diffing
from tests.conftest import (
    ACCEPTANCE_V1,
    APIS_V1,
    RULES_V1,
    change_block,
    commit,
    open_cr,
    publish_v1,
)


def _agent_block(env, ref=None):
    return env["client"].get(
        f"/api/v1/blocks/{ref or env['block_id']}", headers=env["agent"]).json()


# ---------- 验收条件必填 ----------


def test_empty_acceptance_cannot_publish(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = change_block(env, env["block_id"], expect=422, acceptance=[])
    assert r.status_code == 422
    assert any("验收条件" in m for m in r.json()["detail"]["missing"])


def test_acceptance_entry_validation(env):
    r = change_block(env, env["block_id"], expect=422,
                     acceptance=[{"name": "x", "detail": "  "}])
    assert r.status_code == 422
    assert "验收条件" in r.json()["detail"]


def test_nfr_field_is_gone(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    assert "nfr_md" not in _agent_block(env)


# ---------- 稳定 id ----------


def test_ids_are_assigned_on_first_publish_in_order(env):
    change_block(env, env["block_id"],
                 rules=[{"name": "a", "detail": "规则 a"}, {"name": "b", "detail": "规则 b"}],
                 acceptance=[{"name": "x", "detail": "验收 x"}])
    out = _agent_block(env)
    assert [r["id"] for r in out["rules"]] == ["R-1", "R-2"]
    assert [a["id"] for a in out["acceptance"]] == ["AC-1"]


def test_existing_ids_survive_edit_and_reorder(env):
    change_block(env, env["block_id"],
                 rules=[{"name": "a", "detail": "规则 a"}, {"name": "b", "detail": "规则 b"}])
    first = _agent_block(env)["rules"]
    # 调换顺序 + 给 b 改名：id 跟着条目走
    out = change_block(env, env["block_id"], rules=[{**first[1], "name": "b2"}, first[0]])
    assert [(r["id"], r["name"]) for r in _agent_block(env)["rules"]] == [("R-2", "b2"), ("R-1", "a")]
    assert out["delta"]["rules_renamed"] == ["R-2 b2"] and out["level"] == "patch"


def test_ids_are_never_reused_after_delete(env):
    publish_v1(env["client"], env["human"], env["block_id"])  # 发布后快照里有 R-1
    change_block(env, env["block_id"], rules=[{"name": "全新规则", "detail": "删掉旧规则后新增"}])
    assert _agent_block(env)["rules"][0]["id"] == "R-2"  # 不回收已发布过的 R-1


def test_duplicate_or_malformed_ids_rejected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    dup = [{"id": "R-1", "name": "a", "detail": "a"}, {"id": "R-1", "name": "b", "detail": "b"}]
    assert change_block(env, env["block_id"], expect=422, rules=dup).status_code == 422
    bad = [{"id": "AC-1", "name": "a", "detail": "a"}]  # 规则不能用 AC- 前缀
    assert change_block(env, env["block_id"], expect=422, rules=bad).status_code == 422


def test_snapshot_ids_visible_to_agent(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = _agent_block(env)
    assert out["rules"][0]["id"] == "R-1"
    assert out["acceptance"][0]["id"] == "AC-1"


# ---------- 机械版本级别标签 ----------


def test_first_publish_level_is_initial(env):
    body = publish_v1(env["client"], env["human"], env["block_id"])
    assert body["version"] == "1.0.0"
    assert body["level"] == "initial"


def _level_after(env, **change):
    publish_v1(env["client"], env["human"], env["block_id"])
    return change_block(env, env["block_id"], **change)


def test_level_added_rule_is_minor(env):
    body = _level_after(env, rules=[{"id": "R-1", **RULES_V1[0]},
                                    {"name": "新规则", "detail": "新增的规则"}])
    assert (body["level"], body["version"]) == ("minor", "1.1.0")


def test_level_added_acceptance_is_minor(env):
    body = _level_after(env, acceptance=[{"id": "AC-1", **ACCEPTANCE_V1[0]},
                                         {"name": "新验收", "detail": "新增的验收条件"}])
    assert (body["level"], body["version"]) == ("minor", "1.1.0")


def test_level_modified_rule_detail_is_major(env):
    body = _level_after(env, rules=[{"id": "R-1", "name": RULES_V1[0]["name"],
                                     "detail": "完全不同的口径"}])
    assert (body["level"], body["version"]) == ("major", "2.0.0")


def test_level_deleted_rule_is_major(env):
    body = _level_after(env, rules=[{"name": "替代规则", "detail": "删掉 R-1 换一条"}])
    assert body["level"] == "major"
    assert body["delta"]["rules_removed"] == ["R-1 销售额口径"]


def test_level_deleted_acceptance_is_major(env):
    body = _level_after(env, acceptance=[{"name": "别的验收", "detail": "替换掉 AC-1"}])
    assert body["level"] == "major"
    assert body["delta"]["acceptance_removed"] == ["AC-1 日报数据完整"]


def test_level_modified_acceptance_detail_is_major(env):
    body = _level_after(env, acceptance=[{"id": "AC-1", "name": ACCEPTANCE_V1[0]["name"],
                                          "detail": "改成了别的验收标准"}])
    assert body["level"] == "major"


def test_level_rename_only_is_patch(env):
    """只改名称、详述不变：名称只是标签，算 renamed，PATCH。"""
    body = _level_after(env, rules=[{"id": "R-1", "name": "销售额统计口径",
                                     "detail": RULES_V1[0]["detail"]}])
    assert (body["level"], body["version"]) == ("patch", "1.0.1")
    assert body["delta"]["rules_renamed"] == ["R-1 销售额统计口径"]


def test_level_background_only_is_patch(env):
    body = _level_after(env, content_md="# 数据采集模块\n\n只是把背景叙述写得更清楚一些，业务没变。")
    assert (body["level"], body["version"]) == ("patch", "1.0.1")


def test_level_api_field_added_is_minor_and_removal_is_major(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    added = copy.deepcopy(APIS_V1)
    added[0]["response"].append(
        {"name": "note", "type": "string", "required": False, "description": "备注"})
    assert change_block(env, env["block_id"], apis=added)["level"] == "minor"
    # 再把刚加的可选字段删掉：任何删除都是 MAJOR，直接发布，没有确认闸门
    assert change_block(env, env["block_id"], apis=APIS_V1)["level"] == "major"


def test_level_is_recorded_on_versions_and_exposed(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    change_block(env, bid, content_md="# 数据采集模块\n\n只改背景叙述，其余不变，足够二十个字符。")
    versions = c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()
    assert [(v["version"], v["level"]) for v in versions] == [
        ("1.0.0", "initial"), ("1.0.1", "patch")]
    assert c.get(f"/api/v1/blocks/{bid}", headers=a).json()["level"] == "patch"
    assert c.get(f"/api/v1/blocks/{bid}/versions/1.0.0", headers=h).json()["level"] == "initial"
    assert c.get(f"/api/v1/blocks/{bid}/diff", headers=a).json()["level"] == "patch"


def test_dry_run_returns_level(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    r = commit(env, open_cr(env), [{"op": "update_block", "id": bid, "rules": [
        {"id": "R-1", **RULES_V1[0]}, {"name": "新规则", "detail": "新增"}]}], dry_run=True).json()
    b = r["blocks"][0]
    assert (b["version"], b["level"]) == ("1.1.0", "minor")
    assert len(c.get(f"/api/v1/blocks/{bid}/versions", headers=h).json()) == 1  # 预览不落库


@pytest.mark.parametrize(
    "delta,expected",
    [
        ({"added": [], "modified": [], "removed": []}, "patch"),
        ({"added": ["x"], "modified": [], "removed": []}, "minor"),
        ({"added": [], "modified": ["x"], "removed": []}, "major"),
        ({"added": [], "modified": [], "removed": ["x"]}, "major"),
        ({"added": ["x"], "removed": ["y"]}, "major"),
        ({"rules_added": ["R-1 a"]}, "minor"),
        ({"rules_modified": ["R-1 a"]}, "major"),
        ({"rules_removed": ["R-1 a"]}, "major"),
        ({"rules_renamed": ["R-1 a"]}, "patch"),
        ({"acceptance_added": ["AC-1 a"]}, "minor"),
        ({"acceptance_modified": ["AC-1 a"]}, "major"),
        ({"acceptance_removed": ["AC-1 a"]}, "major"),
        ({"acceptance_renamed": ["AC-1 a"]}, "patch"),
    ],
)
def test_bump_level_table(delta, expected):
    """标签完全由 delta 机械算出：一张表覆盖全部分类规则。"""
    assert diffing.bump_level(delta) == expected


# ---------- 派生 Deprecated 状态 ----------


def test_pinned_old_version_is_deprecated_with_superseded_by(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    cur = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert (cur["status"], cur["superseded_by"]) == ("current", None)

    change_block(env, bid, rules=[{"id": "R-1", **RULES_V1[0]}, {"name": "新规则", "detail": "新增"}])

    old = c.get(f"/api/v1/blocks/{bid}@1.0.0", headers=a).json()
    assert (old["status"], old["superseded_by"]) == ("deprecated", "1.1.0")
    new = c.get(f"/api/v1/blocks/{bid}@1.1.0", headers=a).json()
    assert (new["status"], new["superseded_by"]) == ("current", None)


def test_voiding_latest_makes_previous_current_again(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    change_block(env, bid, rules=[{"id": "R-1", **RULES_V1[0]}, {"name": "新规则", "detail": "新增"}])
    assert c.post(f"/api/v1/blocks/{bid}/versions/1.1.0/void", headers=h).status_code == 200
    old = c.get(f"/api/v1/blocks/{bid}@1.0.0", headers=a).json()
    assert (old["status"], old["superseded_by"]) == ("current", None)
