"""一次性数据迁移：legacy proposed_apis（全量替换）折算为 proposed_api_ops（delta）。

折算规则（与 legacy 视图/留痕的折算语义一致）：提案携带的每条 API → upsert；
参照系中存在而提案未携带的条目 → delete（全量替换的隐含删除）。
参照系取提案 base_version 的已发布快照（未作废），取不到回退模块当前已发布
版本，再取不到按空基线——与 proposals/{id}/diff 端点的参照系选择同一规则。

刻意用裸 SQL 而不走 ORM：本脚本在新旧两版代码下都要能跑（新代码里
Proposal 模型已无 proposed_apis_json 列）；键与条目的规范化复用
diffing 的现有函数。幂等：proposed_apis_json 为空的行直接跳过，重复跑无变化。

Usage:
    .venv/Scripts/python scripts/migrate_legacy_proposals.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from speclock import diffing
from speclock.db import get_engine, init_db


def legacy_to_ops(reference: list[dict], proposed: list[dict]) -> list[dict]:
    """全量替换列表折算为 delta ops：提案携带的每条 → upsert；参照系中
    未被携带的条目 → delete（全量替换的隐含删除）。"""
    ops = []
    carried = set()
    for entry in diffing.validate_apis(proposed, require_desc=False):
        carried.add(entry["api"])
        ops.append({"op": "upsert", "api": entry["api"], "entry": entry})
    for e in reference:
        try:
            method, path = diffing.parse_api_name(e.get("api", ""))
        except diffing.ApisValidationError:
            continue
        key = f"{method} {path}"
        if key not in carried:
            ops.append({"op": "delete", "api": key, "entry": None})
    return ops


def _reference_apis(conn, row) -> tuple[list[dict], str]:
    """折算参照系：base_version 快照（未作废）→ 模块当前已发布版本 → 空基线。
    返回 (apis, 描述)。"""
    candidates = [row.base_version]
    current = conn.execute(
        text("SELECT current_published_version FROM blocks WHERE id = :bid"),
        {"bid": row.block_id},
    ).scalar()
    if current and current != row.base_version:
        candidates.append(current)
    for i, version in enumerate(candidates):
        if not version:
            continue
        apis_json = conn.execute(
            text(
                "SELECT apis_json FROM block_versions"
                " WHERE block_id = :bid AND version = :v AND voided_at IS NULL"
            ),
            {"bid": row.block_id, "v": version},
        ).scalar()
        if apis_json is not None:
            suffix = "（回退）" if i > 0 else ""
            return json.loads(apis_json or "[]"), f"v{version}{suffix}"
    return [], "空基线"


def migrate(engine, dry_run: bool = False, log=print) -> int:
    """折算所有 proposed_apis_json 非空的提案，返回处理条数。幂等。"""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, block_id, status, base_version, proposed_apis_json,"
                " proposed_api_ops_json FROM proposals"
                " WHERE proposed_apis_json IS NOT NULL ORDER BY id"
            )
        ).all()
        for row in rows:
            proposed = json.loads(row.proposed_apis_json)
            reference, ref_desc = _reference_apis(conn, row)
            ops = legacy_to_ops(reference, proposed)
            n_upsert = sum(1 for op in ops if op["op"] == "upsert")
            if row.proposed_api_ops_json is not None:
                log(
                    f"proposal #{row.id}（{row.status}）：已有 proposed_api_ops，"
                    f"仅清空 legacy 字段"
                )
            else:
                conn.execute(
                    text(
                        "UPDATE proposals SET proposed_api_ops_json = :ops"
                        " WHERE id = :id"
                    ),
                    {"ops": json.dumps(ops, ensure_ascii=False), "id": row.id},
                )
                log(
                    f"proposal #{row.id}（{row.status}，参照 {ref_desc}）："
                    f"{len(proposed)} 条全量 → {n_upsert} upsert + {len(ops) - n_upsert} delete"
                )
            conn.execute(
                text("UPDATE proposals SET proposed_apis_json = NULL WHERE id = :id"),
                {"id": row.id},
            )
        if not rows:
            log("没有需要迁移的 legacy 提案（幂等：可重复执行）")
        if dry_run:
            conn.rollback()
            log("--dry-run：已回滚，未写入")
        else:
            conn.commit()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印折算结果，不写入")
    args = parser.parse_args()
    engine = get_engine()
    init_db()
    migrate(engine, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
