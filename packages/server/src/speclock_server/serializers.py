"""响应序列化：多个路由共用的 ORM → 响应模型转换。"""

from __future__ import annotations

import json

from speclock_core import BlockOut, BlockVersion, ExecutionRecord, executions


def block_out(bv: BlockVersion, recs: list[ExecutionRecord] | None = None) -> BlockOut:
    ex = executions.exec_fields(recs or [])
    block = bv.block
    return BlockOut(
        block_id=bv.block_id,
        title=block.title,
        version=bv.version,
        content_md=bv.content_md,
        rules=json.loads(bv.rules_json or "[]"),
        acceptance=json.loads(bv.acceptance_json or "[]"),
        apis=json.loads(bv.apis_json or "[]"),
        openapi_yaml=bv.openapi_yaml,
        change_note=bv.change_note,
        level=bv.level,
        # 派生状态：不是最新未作废版本就是 deprecated（pin 旧版本的 agent 由此得知已过期）
        status="current" if bv.version == block.current_published_version else "deprecated",
        superseded_by=(
            None if bv.version == block.current_published_version
            else block.current_published_version
        ),
        delta=json.loads(bv.delta_json),
        published_at=bv.published_at,
        surfaces=json.loads(bv.surfaces_json or "[]"),
        work_id=ex["work_id"],
        execution_status=ex["execution_status"],
        works=ex["works"],
        cr_id=bv.cr_id,
        commit_id=bv.commit_id,
    )
