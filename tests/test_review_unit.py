"""语义复核的单元测试：编辑距离、判定函数、配置读取、权限迁移、kind 回显校验。"""

from __future__ import annotations

import json

from speclock import review
from speclock.db import SessionLocal
from speclock.models import MigrationMark, Role
from speclock.permissions import seed_roles
from speclock.settings import ReviewSettings, load_settings

CFG = ReviewSettings()
BASE = "支付成功订单金额合计（不含退款）"
TYPO = "支付成功订单金额合计(不含退款)"  # 2 个字，占 12.5%


def _blk(rules=(), acceptance=(), apis=(), title="模块"):
    return {"title": title, "rules": list(rules), "acceptance": list(acceptance), "apis": list(apis)}


def _rule(i, detail, name="规则"):
    return {"id": f"R-{i}", "name": name, "detail": detail}


def test_edit_distance():
    assert review.edit_distance("abc", "abc") == 0
    assert review.edit_distance("kitten", "sitting") == 3
    assert review.edit_distance("", "abc") == 3
    assert review.edit_distance("无缺失门店", "无缺失门点") == 1
    assert review.edit_distance("a" * 50, "b" * 50, limit=3) == 4  # 超过上限提前返回 limit + 1


def test_tiers():
    before = {1: _blk([_rule(1, BASE)])}
    same = {1: _blk([_rule(1, BASE)])}
    assert review.classify(before, same, CFG).tier == 1
    # 搬到另一个模块：条目总和不变 → 第 1 档
    moved = {1: _blk([]), 2: _blk([_rule(1, BASE)])}
    assert review.classify(before, moved, CFG).tier == 1
    # 单条小改动 → 第 2 档
    typo = {1: _blk([_rule(1, TYPO)])}
    v = review.classify(before, typo, CFG)
    assert v.tier == 2 and v.changes[0]["item_id"] == "R-1" and v.changes[0]["distance"] <= 6
    # 整条重写 → 第 3 档
    rewrite = {1: _blk([_rule(1, "按下单时间统计的全部金额之和，包含退款订单")])}
    v = review.classify(before, rewrite, CFG)
    assert v.tier == 3 and "改动" in v.substantive[0]["why"]
    # 新增 / 删除条目 → 第 3 档
    assert review.classify(before, {1: _blk([_rule(1, BASE), _rule(2, "新的一条规则")])}, CFG).tier == 3
    assert review.classify(before, {1: _blk([])}, CFG).tier == 3


def test_identity_is_by_id_not_name():
    before = {1: _blk([_rule(1, BASE, name="销售额口径")])}
    # 名称相同、id 不同：不是同一条 → 新增 + 删除
    after = {1: _blk([_rule(9, TYPO, name="销售额口径")])}
    v = review.classify(before, after, CFG)
    assert v.tier == 3
    whys = " ".join(x["why"] for x in v.substantive)
    assert "新增" in whys and "删除" in whys


def test_thresholds_are_configurable():
    before = {1: _blk([_rule(1, BASE)])}
    after = {1: _blk([_rule(1, TYPO)])}
    assert review.classify(before, after, ReviewSettings(max_edit_chars=1)).tier == 3
    assert review.classify(before, after, ReviewSettings(max_edit_ratio=0.01)).tier == 3
    assert review.classify(before, after, ReviewSettings(enabled=False)).tier == 3
    assert review.classify(before, after, ReviewSettings(max_edit_chars=2, max_edit_ratio=0.5)).tier == 2


def test_verdict_fingerprint_is_stable():
    before = {1: _blk([_rule(1, "甲乙丙丁戊己庚辛"), _rule(2, "子丑寅卯辰巳午未")])}
    after = {1: _blk([_rule(1, "甲乙丙丁戊己庚壬"), _rule(2, "子丑寅卯辰巳午申")])}
    v = review.classify(before, after, CFG)
    assert v.tier == 2 and len(v.fingerprint()) == 2 and v.fingerprint() == sorted(v.fingerprint())


def test_review_settings_are_read_from_toml(tmp_path, monkeypatch):
    f = tmp_path / "c.toml"
    f.write_text('active = "local"\n[local]\ndb_url = "sqlite:///x.db"\n[review]\nmax_entries = 9\nmax_edit_ratio = 0.3\nenabled = false\n', encoding="utf-8")
    monkeypatch.setenv("SPECLOCK_CONFIG", str(f))
    cfg = load_settings().review
    assert (cfg.max_entries, cfg.max_edit_ratio, cfg.enabled, cfg.max_edit_chars) == (9, 0.3, False, 6)
    # 不写 [review] 节就用保守的默认值
    f.write_text('active = "local"\n[local]\ndb_url = "sqlite:///x.db"\n', encoding="utf-8")
    assert load_settings().review == ReviewSettings()


def test_cr_review_permission_is_migrated_once(env):
    db = SessionLocal()
    try:
        for name in ("scanner-agent", "reviewer", "admin"):
            role = db.query(Role).filter(Role.name == name).one()
            role.permissions_json = json.dumps([p for p in json.loads(role.permissions_json) if p != "cr.review"])
        db.query(MigrationMark).filter(MigrationMark.name == "cr_review_permission").delete()
        db.commit()
        seed_roles(db)
        for name in ("scanner-agent", "reviewer", "admin"):
            assert "cr.review" in json.loads(db.query(Role).filter(Role.name == name).one().permissions_json)
        # 管理员之后收回，不会被重新补上；需求 Agent 从来没有
        role = db.query(Role).filter(Role.name == "scanner-agent").one()
        role.permissions_json = json.dumps(["spec.read"])
        db.commit()
        seed_roles(db)
        db.refresh(role)
        assert "cr.review" not in json.loads(role.permissions_json)
        assert "cr.review" not in json.loads(db.query(Role).filter(Role.name == "requirements-agent").one().permissions_json)
    finally:
        db.close()


def test_kind_echo_catches_an_old_server_that_drops_kind():
    from speclock import mcp_server

    old_server = json.dumps({"status": 201, "body": {"id": 7, "status": "draft", "title": "x"}})  # 没有 kind
    out = json.loads(mcp_server._kind_echo(old_server, "internal"))
    assert "没有认出" in out["error"] and out["created"]["id"] == 7
    ok = json.dumps({"status": 201, "body": {"id": 7, "kind": "internal"}})
    assert mcp_server._kind_echo(ok, "internal") == ok
    assert mcp_server._kind_echo(old_server, "business") == old_server  # 默认值不校验
    assert mcp_server._kind_echo(old_server, None) == old_server
    err = json.dumps({"status": 422, "body": {"detail": "x"}})
    assert mcp_server._kind_echo(err, "internal") == err  # 请求本来就失败了，别再包一层
