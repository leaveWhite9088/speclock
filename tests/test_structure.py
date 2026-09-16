"""业务描述结构化拆分：发布关口的结构完备性校验、规则清单 delta、
agent 读面新字段、编辑器/UI 新区块、存量库增量迁移幂等。"""

from __future__ import annotations

import json

from tests.conftest import APIS_NO_DESC, APIS_V1, RULES_V1, publish_v1


# ---------- 结构完备性：缺 desc ----------

def test_api_without_desc_cannot_be_saved(env):
    r = env["client"].put(
        f"/api/v1/blocks/{env['block_id']}", json={"apis": APIS_NO_DESC},
        headers=env["human"],
    )
    assert r.status_code == 422
    assert "desc" in r.json()["detail"]


def test_api_without_desc_cannot_publish(env):
    """脏数据绕过保存校验（直接落库）时，发布关口依然拦下并指明是哪条 API。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    from speclock.db import SessionLocal
    from speclock.models import Block

    db = SessionLocal()
    block = db.get(Block, bid)
    block.draft_apis_json = json.dumps(APIS_NO_DESC, ensure_ascii=False)
    db.commit()
    db.close()
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "x", "fastTrack": True}, headers=h)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "模块结构不完备，不能发布"
    assert any("拉取日报主表" in m and "desc" in m for m in detail["missing"])


def test_proposal_apis_without_desc_rejected(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].post(
        "/api/v1/proposals",
        json={"block_id": env["block_id"], "description": "d", "suggestion": "s",
              "proposed_apis": APIS_NO_DESC},
        headers=env["agent"],
    )
    assert r.status_code == 422


# ---------- 结构完备性：rules / 背景叙述 ----------

def test_empty_rules_cannot_publish(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    r = c.put(f"/api/v1/blocks/{bid}", json={"rules": []}, headers=h)
    assert r.status_code == 200  # 保存允许空清单（草稿态自由）
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "x", "fastTrack": True}, headers=h)
    assert r.status_code == 422
    assert any("规则" in m for m in r.json()["detail"]["missing"])


def test_rule_with_empty_detail_cannot_be_saved(env):
    r = env["client"].put(
        f"/api/v1/blocks/{env['block_id']}",
        json={"rules": [{"name": "销售额口径", "detail": "  "}]},
        headers=env["human"],
    )
    assert r.status_code == 422
    assert "detail" in r.json()["detail"]


def test_short_content_md_cannot_publish(env):
    """背景叙述不足 20 字符时 422，且 detail 一次列出全部缺失项。"""
    c, h, bid = env["client"], env["human"], env["block_id"]
    # apis 缺 desc 走保存校验 422（整个 PUT 不落库）
    r = c.put(f"/api/v1/blocks/{bid}",
              json={"content_md": "太短", "rules": [], "apis": APIS_NO_DESC}, headers=h)
    assert r.status_code == 422
    # 合法 apis + 过短背景 + 空规则：发布关口一次报出全部缺失项
    c.put(f"/api/v1/blocks/{bid}",
          json={"content_md": "太短", "rules": [], "apis": APIS_V1}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "x", "fastTrack": True}, headers=h)
    assert r.status_code == 422
    missing = r.json()["detail"]["missing"]
    assert any("业务背景" in m for m in missing)
    assert any("规则" in m for m in missing)
    assert len(missing) == 2  # apis 已合法，不应再出现 desc 项


def test_dryrun_also_gated_by_readiness(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"rules": []}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish", json={"dryRun": True}, headers=h)
    assert r.status_code == 422


# ---------- rules 结构化 delta ----------

def test_rules_delta_in_publish_and_diff(env):
    c, h, a, bid = env["client"], env["human"], env["agent"], env["block_id"]
    publish_v1(c, h, bid)
    rules_v2 = [
        {"name": "销售额口径", "detail": "支付成功订单金额合计（含退款）"},  # detail 改 → modified
        {"name": "新增规则", "detail": "每日 06:30 前必须完成采集"},  # added
    ]  # 不再有其他规则 → RULES_V1 之外的视为 removed（此处 RULES_V1 只有一条且被改）
    c.put(f"/api/v1/blocks/{bid}", json={"rules": rules_v2}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "改规则", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delta"]["rules_added"] == ["新增规则"]
    assert body["delta"]["rules_modified"] == ["销售额口径"]
    assert body["delta"]["rules_removed"] == []
    assert body["breaking"] is False  # rules 变化不算破坏性
    assert body["version"] == "1.0.1"  # 无 API 新增 → PATCH

    # 快照上保留了 rules；agent 读面可见
    out = c.get(f"/api/v1/blocks/{bid}", headers=a).json()
    assert [r["name"] for r in out["rules"]] == ["销售额口径", "新增规则"]
    assert out["apis"][0]["desc"]
    assert "edge_md" in out

    # agent diff 响应带 rules delta
    r = c.get(f"/api/v1/blocks/{bid}/diff",
              params={"from": "1.0.0", "to": "1.0.1"}, headers=a)
    d = r.json()["delta"]
    assert d["rules_added"] == ["新增规则"]
    assert d["rules_modified"] == ["销售额口径"]

    # 再删一条规则 → rules_removed
    c.put(f"/api/v1/blocks/{bid}", json={"rules": rules_v2[:1]}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "删规则", "fastTrack": True}, headers=h)
    assert r.status_code == 200
    assert r.json()["delta"]["rules_removed"] == ["新增规则"]
    assert r.json()["breaking"] is False


# ---------- UI 新区块 ----------

def test_editor_page_has_structured_sections(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    body = env["client"].get(
        f"/ui/blocks/{env['block_id']}?key={env['human']['X-API-Key']}"
    ).text
    assert "业务背景与流程" in body
    assert "业务规则清单" in body
    assert "边界与异常" in body
    assert 'id="rule-list"' in body
    assert 'id="rules-data"' in body
    assert 'id="edge_md"' in body
    assert "端点语义" in body  # API 卡片里的 desc 输入


def test_view_page_shows_rules_and_sections(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    body = c.get(f"/ui/blocks/{env['block_id']}/view?key={h['X-API-Key']}").text
    assert "业务背景与流程" in body
    assert "业务规则清单" in body
    assert "销售额口径" in body  # RULES_V1 的规则名出现在只读视图
    assert "端点语义" in body


def test_diff_page_shows_rules_changes(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    c.put(f"/api/v1/blocks/{env['block_id']}",
          json={"rules": RULES_V1 + [{"name": "采集时限", "detail": "06:30 前完成"}]},
          headers=h)
    c.post(f"/api/v1/blocks/{env['block_id']}/publish",
           json={"change_note": "加规则", "fastTrack": True}, headers=h)
    body = c.get(f"/ui/blocks/{env['block_id']}/diff?key={h['X-API-Key']}").text
    assert "业务规则变更" in body
    assert "采集时限" in body


# ---------- 存量库增量迁移（幂等） ----------

def test_init_db_migrates_legacy_db_idempotently(tmp_path):
    """模拟老库（blocks 表没有 rules/edge 两列、apis 无 desc）：
    init_db 跑两次不报错；列被补齐；缺 desc 的 API 回填 desc = name。"""
    import os
    import sqlite3

    from speclock.db import SessionLocal, configure, init_db
    from speclock.models import Block

    url = f"sqlite:///{tmp_path}/legacy.db"
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute(
        """
        CREATE TABLE blocks (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
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
        "INSERT INTO blocks (document_id, title, draft_content_md, draft_apis_json)"
        " VALUES (1, '老模块', '老库遗留的背景叙述文字，足够长。', ?)",
        (json.dumps([
            {"name": "查", "api": "GET /api/x", "request": [], "response": []},
            {"name": "增", "api": "POST /api/x", "desc": "已有 desc 不动",
             "request": [], "response": []},
        ], ensure_ascii=False),),
    )
    conn.commit()
    conn.close()

    configure(url)
    try:
        init_db()
        init_db()  # 第二次：幂等，不报错
        db = SessionLocal()
        block = db.query(Block).one()
        assert block.draft_rules_json == "[]"  # rules 刻意不回填
        assert block.draft_edge_md == ""
        apis = json.loads(block.draft_apis_json)
        assert apis[0]["desc"] == "查"  # 缺 desc → 回填为 name
        assert apis[1]["desc"] == "已有 desc 不动"
        db.close()
        # 再跑第三次确认回填也是幂等的（不产生额外写入差异）
        init_db()
        db = SessionLocal()
        apis2 = json.loads(db.query(Block).one().draft_apis_json)
        db.close()
        assert apis2 == apis
    finally:
        configure(os.environ["SPECLOCK_DB_URL"])
