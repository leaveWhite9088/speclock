"""业务描述结构化拆分：发布关口的结构完备性校验、规则清单 delta、
agent 读面新字段、结构化区块的 API 读取、存量库增量迁移幂等。
（写入一律经由审核单下的 Commit。）"""

from __future__ import annotations

import json

from tests.conftest import (
    APIS_NO_DESC,
    APIS_V1,
    RULES_V1,
    change_block,
    commit,
    open_cr,
    publish_v1,
)


# ---------- 结构完备性：缺 desc ----------

def test_api_without_desc_cannot_be_written(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = change_block(env, env["block_id"], expect=422, apis=APIS_NO_DESC)
    assert r.status_code == 422
    # desc 缺失现在和其他缺失项一起由发布关口列在 missing 里
    assert any("desc" in m for m in r.json()["detail"]["missing"])


def test_api_without_desc_cannot_publish(env):
    """脏数据绕过写入校验（直接落库）时，发布关口依然拦下并指明是哪条 API。"""
    from speclock_core import SessionLocal
    from speclock_core import Block

    publish_v1(env["client"], env["human"], env["block_id"])
    db = SessionLocal()
    block = db.get(Block, env["block_id"])
    block.draft_apis_json = json.dumps(APIS_NO_DESC, ensure_ascii=False)
    db.commit()
    db.close()
    r = change_block(env, env["block_id"], expect=422,
                     content_md="# 数据采集模块\n\n触发一次发布，但脏数据里的 API 没有 desc。")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "模块结构不完备，不能发布"
    assert any("拉取日报主表" in m and "desc" in m for m in detail["missing"])


def test_api_ops_without_desc_rejected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = change_block(env, env["block_id"], expect=422, api_ops=[
        {"op": "upsert", "api": APIS_NO_DESC[0]["api"], "entry": APIS_NO_DESC[0]}])
    assert r.status_code == 422


# ---------- 结构完备性：rules / 背景叙述 ----------

def test_empty_rules_cannot_publish(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = change_block(env, env["block_id"], expect=422, rules=[])
    assert r.status_code == 422
    assert any("规则" in m for m in r.json()["detail"]["missing"])


def test_rule_with_empty_detail_cannot_be_written(env):
    r = change_block(env, env["block_id"], expect=422,
                     rules=[{"name": "销售额口径", "detail": "  "}])
    assert r.status_code == 422
    assert "detail" in r.json()["detail"]


def test_short_content_md_cannot_publish(env):
    """背景叙述不足 20 字符时 422，且 detail 一次列出全部缺失项。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    # apis 缺 desc 在写入校验就 422（整个 Commit 不落库）
    r = change_block(env, env["block_id"], expect=422,
                     content_md="太短", rules=[], apis=APIS_NO_DESC)
    assert r.status_code == 422
    # 合法 apis + 过短背景 + 空规则：发布关口一次报出全部缺失项
    r = change_block(env, env["block_id"], expect=422,
                     content_md="太短", rules=[], apis=APIS_V1)
    assert r.status_code == 422
    missing = r.json()["detail"]["missing"]
    assert any("业务背景" in m for m in missing)
    assert any("规则" in m for m in missing)
    assert len(missing) == 2  # apis 已合法，不应再出现 desc 项


def test_dryrun_also_gated_by_readiness(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env),
               [{"op": "update_block", "id": env["block_id"], "rules": []}], dry_run=True)
    assert r.status_code == 422


# ---------- rules 结构化 delta ----------

def test_rules_delta_in_publish_and_diff(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    rules_v2 = [
        # R-1：detail 改 → modified（规则改动按保守一侧标 MAJOR）
        {"id": "R-1", "name": "销售额口径", "detail": "支付成功订单金额合计（含退款）"},
        {"name": "新增规则", "detail": "每日 06:30 前必须完成采集"},  # 无 id → 新增，分配 R-2
    ]
    body = change_block(env, bid, rules=rules_v2, note="改规则")
    assert body["delta"]["rules_added"] == ["R-2 新增规则"]
    assert body["delta"]["rules_modified"] == ["R-1 销售额口径"]
    assert body["delta"]["rules_removed"] == []
    assert body["level"] == "major"  # 规则被修改 → MAJOR
    assert body["version"] == "2.0.0"

    # 快照上保留了 rules（带稳定 id）；agent 读面可见
    out = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert [(r["id"], r["name"]) for r in out["rules"]] == [
        ("R-1", "销售额口径"), ("R-2", "新增规则")]
    assert out["apis"][0]["desc"]
    assert "edge_md" not in out and "nfr_md" not in out

    # agent diff 响应带 rules delta 与机械标签
    r = c.get(f"/api/v1/blocks/{bid}/diff",
              params={"from": "1.0.0", "to": "2.0.0"}, headers=a)
    d = r.json()["delta"]
    assert d["rules_added"] == ["R-2 新增规则"]
    assert d["rules_modified"] == ["R-1 销售额口径"]
    assert r.json()["level"] == "major"

    # 再删一条规则 → rules_removed，仍是 MAJOR
    body = change_block(env, bid, rules=rules_v2[:1], note="删规则")
    assert body["delta"]["rules_removed"] == ["R-2 新增规则"]
    assert body["level"] == "major"
    assert body["version"] == "3.0.0"


# ---------- 结构化区块的 API 读取（SPA 的数据源） ----------

def test_version_api_returns_rules_and_sections(env):
    """对应 SPA 只读视图：已发布版本快照含规则清单、验收条件与端点语义。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    v = c.get(
        f"/api/v1/blocks/{env['block_id']}/versions/1.0.0", headers=h
    ).json()
    assert v["content_md"].startswith("# 数据采集模块")
    assert [(r["name"], r["detail"]) for r in v["rules"]] == [
        (r["name"], r["detail"]) for r in RULES_V1]
    assert [r["id"] for r in v["rules"]] == ["R-1"]
    assert [r["id"] for r in v["acceptance"]] == ["AC-1"]
    assert "nfr_md" not in v
    assert v["apis"][0]["desc"]  # 端点语义


def test_diff_api_returns_rules_changes(env):
    """对应 SPA diff 视图：diff 端点的规则 delta（有 spec.read 的 key 都能读）。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    change_block(env, env["block_id"], note="加规则",
                 rules=[{"id": "R-1", **RULES_V1[0]}, {"name": "采集时限", "detail": "06:30 前完成"}])
    d = c.get(f"/api/v1/blocks/{env['block_id']}/diff", headers=h).json()
    assert (d["from"], d["to"]) == ("1.0.0", "1.1.0")  # 只有新增 → MINOR
    assert d["delta"]["rules_added"] == ["R-2 采集时限"]
    assert d["level"] == "minor"


# ---------- 存量库增量迁移（幂等） ----------

def test_init_db_migrates_legacy_db_idempotently(tmp_path):
    """模拟老库（blocks 表缺 rules / acceptance 列，还带已废弃的 nfr 列）：
    init_db 跑两次不报错；缺的列被补齐，已废弃的列被删除；预置角色就位，没有角色的老
    key 回填默认角色。"""
    import os
    import sqlite3

    from speclock_core import SessionLocal, configure, init_db
    from speclock_core import ApiKey, Block, Role

    url = f"sqlite:///{tmp_path}/legacy.db"
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute(
        """
        CREATE TABLE blocks (
            id INTEGER PRIMARY KEY,
            capability_id INTEGER NOT NULL,
            title VARCHAR NOT NULL,
            summary VARCHAR NOT NULL DEFAULT '',
            status VARCHAR NOT NULL DEFAULT 'draft',
            current_published_version VARCHAR,
            archived_at DATETIME,
            completed BOOLEAN NOT NULL DEFAULT 0,
            completed_version VARCHAR,
            completed_at DATETIME,
            draft_content_md TEXT NOT NULL DEFAULT '',
            draft_apis_json TEXT NOT NULL DEFAULT '[]',
            draft_nfr_md TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "INSERT INTO blocks (capability_id, title, draft_content_md) VALUES (1, '老模块', '老库遗留的背景叙述')"
    )
    conn.execute(
        "CREATE TABLE api_keys (id INTEGER PRIMARY KEY, key VARCHAR NOT NULL UNIQUE,"
        " hint VARCHAR NOT NULL DEFAULT '', prefix VARCHAR NOT NULL, project_id INTEGER,"
        " label VARCHAR NOT NULL DEFAULT '', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO api_keys (key, prefix) VALUES (?, ?)", [("h" * 64, "human"), ("a" * 64, "agent")]
    )
    conn.commit()
    conn.close()

    configure(url)
    try:
        init_db()
        init_db()  # 第二次：幂等，不报错
        db = SessionLocal()
        block = db.query(Block).one()
        assert block.draft_rules_json == "[]" and block.draft_acceptance_json == "[]"
        cols = {r[1] for r in db.execute(__import__("sqlalchemy").text("PRAGMA table_info(blocks)"))}
        assert "draft_nfr_md" not in cols
        assert db.query(Role).count() == 7
        assert "completed" not in cols and "completed_version" not in cols
        roles = {k.prefix: k.role.name for k in db.query(ApiKey).all()}
        assert roles == {"human": "admin", "agent": "executor-agent"}
        db.close()
    finally:
        configure(os.environ["SPECLOCK_DB_URL"])
