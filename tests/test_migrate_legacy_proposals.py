"""scripts/migrate_legacy_proposals.py：legacy 全量提案 → delta ops 的一次性迁移。

覆盖：折算规则（upsert + 隐含 delete）、端到端迁移后现有读取面（get_proposal /
diff 端点）渲染等价视图、幂等、base 快照作废回退、空基线、--dry-run 回滚。
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

from sqlalchemy import text

from speclock.api_admin import _apply_api_ops
from speclock.db import SessionLocal, get_engine
from tests.conftest import APIS_V1, publish_v1

_SPEC = importlib.util.spec_from_file_location(
    "migrate_legacy_proposals",
    Path(__file__).resolve().parent.parent / "scripts" / "migrate_legacy_proposals.py",
)
mig = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mig)

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

_QUIET = lambda *args: None  # noqa: E731


def _ensure_legacy_column(conn) -> None:
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(proposals)"))}
    if "proposed_apis_json" not in cols:
        conn.execute(text("ALTER TABLE proposals ADD COLUMN proposed_apis_json TEXT"))


def _make_legacy_proposal(env, proposed, base_version="1.0.0", status="published") -> int:
    """新模型已无 legacy 列：走 ORM 建行，再用裸 SQL 写入 legacy 载荷。"""
    from speclock.models import Proposal

    db = SessionLocal()
    p = Proposal(
        block_id=env["block_id"],
        author_type="agent",
        description="d",
        suggestion="s",
        base_version=base_version,
        status=status,
    )
    db.add(p)
    db.commit()
    pid = p.id
    db.close()
    with get_engine().begin() as conn:
        _ensure_legacy_column(conn)
        conn.execute(
            text("UPDATE proposals SET proposed_apis_json = :j WHERE id = :id"),
            {"j": json.dumps(proposed, ensure_ascii=False), "id": pid},
        )
    return pid


def _legacy_payload(pid):
    with get_engine().connect() as conn:
        return conn.execute(
            text(
                "SELECT proposed_apis_json, proposed_api_ops_json"
                " FROM proposals WHERE id = :id"
            ),
            {"id": pid},
        ).one()


def _changed_entry():
    entry = copy.deepcopy(APIS_V1[0])
    entry["desc"] = "改写后的端点语义（整体替换提案）"
    return entry


def test_legacy_to_ops_upsert_and_implicit_delete():
    ops = mig.legacy_to_ops(APIS_TWO, [_changed_entry()])
    assert [op["op"] for op in ops] == ["upsert", "delete"]
    assert ops[0]["api"] == "GET /api/daily-report"
    assert ops[0]["entry"]["desc"] == "改写后的端点语义（整体替换提案）"
    assert ops[1] == {"op": "delete", "api": "GET /api/collect-status", "entry": None}
    # ops 应用到参照系可还原原全量列表
    merged = _apply_api_ops(APIS_TWO, ops)
    assert [e["api"] for e in merged] == ["GET /api/daily-report"]
    assert merged[0]["desc"] == "改写后的端点语义（整体替换提案）"


def test_migrate_end_to_end_renders_equivalent_view(env):
    c, h, a = env["client"], env["human"], env["agent"]
    publish_v1(c, h, env["block_id"], apis=APIS_TWO)
    pid = _make_legacy_proposal(env, [_changed_entry()])

    assert mig.migrate(get_engine(), log=_QUIET) == 1

    legacy, ops_json = _legacy_payload(pid)
    assert legacy is None
    ops = json.loads(ops_json)
    assert [op["op"] for op in ops] == ["upsert", "delete"]

    # agent 轮询：载荷以 ops 形态可见
    p = c.get(f"/api/v1/proposals/{pid}", headers=a).json()
    assert p["proposed_api_ops"][0]["api"] == "GET /api/daily-report"

    # diff 端点：相对 base 快照渲染出 upsert（旧 desc 对照）+ 隐含 delete
    d = c.get(f"/api/v1/proposals/{pid}/diff", headers=a).json()
    assert d["base_version"] == "1.0.0"
    assert [ch["op"] for ch in d["api_changes"]] == ["upsert", "delete"]
    up, delete = d["api_changes"]
    assert up["current_entry"]["desc"] == APIS_V1[0]["desc"]
    desc_change = next(x for x in up["changes"]["text"] if x["path"] == "desc")
    assert desc_change["old"] == APIS_V1[0]["desc"]
    assert desc_change["new"] == "改写后的端点语义（整体替换提案）"
    assert delete["api"] == "GET /api/collect-status"
    assert delete["current_entry"]["response"][0]["name"] == "status"

    # 管理端收件箱同样以 enriched ops 渲染
    inbox = c.get("/api/v1/proposals", headers=h).json()
    item = next(x for x in inbox if x["id"] == pid)
    assert [op["op"] for op in item["proposed_api_ops"]] == ["upsert", "delete"]
    assert "proposed_apis" not in item


def test_migrate_is_idempotent(env):
    publish_v1(env["client"], env["human"], env["block_id"], apis=APIS_TWO)
    pid = _make_legacy_proposal(env, [_changed_entry()])

    assert mig.migrate(get_engine(), log=_QUIET) == 1
    _, ops_after_first = _legacy_payload(pid)
    assert mig.migrate(get_engine(), log=_QUIET) == 0
    legacy, ops_after_second = _legacy_payload(pid)
    assert legacy is None
    assert ops_after_second == ops_after_first


def test_migrate_base_voided_falls_back_to_current(env):
    """base 快照已作废：参照系回退当前已发布版本。"""
    c, h, a = env["client"], env["human"], env["agent"]
    bid = env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)
    pid = _make_legacy_proposal(env, [_changed_entry()], base_version="1.0.0")

    # 发布 1.0.1（仅改正文），再作废 1.0.0
    r = c.put(f"/api/v1/blocks/{bid}",
              json={"content_md": "# 数据采集模块\n\n每日 06:00 汇总前一日经营数据并归档。"},
              headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": "v1.0.1", "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/blocks/{bid}/versions/1.0.0/void", headers=h)
    assert r.status_code == 200, r.text

    assert mig.migrate(get_engine(), log=_QUIET) == 1
    _, ops_json = _legacy_payload(pid)
    ops = json.loads(ops_json)
    # 参照 1.0.1 快照（两条 API）：隐含 delete 依然折算得出
    assert [op["op"] for op in ops] == ["upsert", "delete"]

    d = c.get(f"/api/v1/proposals/{pid}/diff", headers=a).json()
    assert d["base_version"] == "1.0.1"
    assert d["base_is_recorded"] is False
    assert d["api_changes"][0]["current_entry"] is not None


def test_migrate_empty_baseline_all_upserts(env):
    """所有快照不可用：按空基线折算，全部为 upsert、无 delete。"""
    c, h = env["client"], env["human"]
    bid = env["block_id"]
    publish_v1(c, h, bid, apis=APIS_TWO)
    pid = _make_legacy_proposal(env, [_changed_entry()], base_version=None)
    # base 为空 → 回退当前已发布版本；把它也作废 → 空基线
    r = c.post(f"/api/v1/blocks/{bid}/versions/1.0.0/void", headers=h)
    assert r.status_code == 200, r.text

    assert mig.migrate(get_engine(), log=_QUIET) == 1
    _, ops_json = _legacy_payload(pid)
    ops = json.loads(ops_json)
    assert [op["op"] for op in ops] == ["upsert"]


def test_migrate_dry_run_rolls_back(env):
    publish_v1(env["client"], env["human"], env["block_id"], apis=APIS_TWO)
    pid = _make_legacy_proposal(env, [_changed_entry()])

    assert mig.migrate(get_engine(), dry_run=True, log=_QUIET) == 1
    legacy, ops_json = _legacy_payload(pid)
    assert legacy is not None  # 未写入
    assert ops_json is None
