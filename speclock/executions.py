"""执行记录：规格发布之后，「把它实现出来」这件事的状态机（与规格状态分开存放）。

Core 只做机械的事——登记、转换、校验、留痕；谁来做、怎么做、做得好不好由外部 Agent 负责。

- 每个已发布的模块版本自动有一条记录（``sync_block``，由发布引擎在发布后调用）；
  同一模块发布新版本时，旧版本上未结束的记录变 ``superseded``。
- 状态：``pending`` → ``in_progress``（领取）→ ``implemented``（逐条验收条件自测全部通过）
  → ``verified``（独立验证者逐条确认）。``in_progress`` 还可以去 ``blocked`` / ``failed``，
  这两个状态可以重新领取；验收不通过也回到 ``failed``。``verified`` / ``superseded`` 是终态。
- 验证者不能是实现者（按 key 判定）——「不靠 Agent 自报」是机械规则，不靠提示词。
- 每次转换写一条只追加的 ``ExecutionEvent``。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session

from speclock.auth import audit
from speclock.models import (
    ApiKey,
    Block,
    BlockVersion,
    ExecutionEvent,
    ExecutionRecord,
    utcnow,
)

OPEN_STATUSES = ("pending", "in_progress", "blocked", "failed", "implemented")
CLAIMABLE = ("pending", "failed", "blocked")
ALL_STATUSES = (*OPEN_STATUSES, "verified", "superseded")


def _transition(
    db: Session,
    rec: ExecutionRecord,
    event: str,
    to: str,
    actor: str,
    note: str = "",
    detail: dict | None = None,
) -> None:
    db.add(
        ExecutionEvent(
            record=rec,
            event=event,
            from_status=rec.status,
            to_status=to,
            actor=actor,
            note=note,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
    rec.status = to
    rec.updated_at = utcnow()
    audit(db, actor, f"exec_{event}", f"work:{rec.block_id}@{rec.version}",
          {"status": to, "note": note})


def sync_block(db: Session, block: Block, actor: str) -> ExecutionRecord | None:
    """让执行记录跟上模块的当前已发布版本（幂等）：
    - 当前版本没有记录就建一条 pending；
    - 该模块其它版本上未结束的记录 → superseded。
    不改变 verified 的记录。未发布 / 已归档的模块不建记录。"""
    if block.status != "published" or block.current_published_version is None:
        return None
    current = block.current_published_version
    records = db.query(ExecutionRecord).filter(ExecutionRecord.block_id == block.id).all()
    mine = None
    for rec in records:
        if rec.version == current:
            mine = rec
        elif rec.status in OPEN_STATUSES:
            _transition(db, rec, "superseded", "superseded", actor,
                        f"模块已发布新版本 {current}", {"superseded_by": current})
    if mine is None:
        mine = ExecutionRecord(block_id=block.id, version=current, status="pending")
        db.add(mine)
        db.flush()
        db.add(
            ExecutionEvent(record=mine, event="created", from_status="", to_status="pending",
                           actor=actor, note=f"版本 {current} 发布，等待领取")
        )
    return mine


def backfill(db: Session) -> None:
    """给已有的已发布模块补执行记录（老库升级 / seed 之后）。"""
    for block in db.query(Block).filter(Block.status == "published").all():
        sync_block(db, block, "system")
    db.commit()


def current_record(db: Session, block: Block) -> ExecutionRecord | None:
    if block.current_published_version is None:
        return None
    return (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.block_id == block.id,
            ExecutionRecord.version == block.current_published_version,
        )
        .first()
    )


def version_acceptance(db: Session, rec: ExecutionRecord) -> list[dict]:
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == rec.block_id, BlockVersion.version == rec.version)
        .first()
    )
    return json.loads(bv.acceptance_json or "[]") if bv else []


# ---------- 守卫 ----------


def _require_current(rec: ExecutionRecord) -> None:
    block = rec.block
    if rec.status == "superseded" or rec.version != block.current_published_version:
        latest = current_record(object_session(rec), block)
        raise HTTPException(
            status_code=409,
            detail={
                "error": f"这条记录针对的版本 {rec.version} 已被取代，请改去处理最新版本",
                "latest_version": block.current_published_version,
                "latest_work_id": latest.id if latest else None,
            },
        )
    if block.status != "published":
        raise HTTPException(status_code=409, detail=f"模块 {block.id} 已归档，暂不能处理")


def _require_status(rec: ExecutionRecord, allowed: tuple[str, ...], action: str) -> None:
    if rec.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"当前状态是 {rec.status}，不能{action}（需要处于：{'、'.join(allowed)}）",
        )


def _require_holder(rec: ExecutionRecord, key: ApiKey) -> None:
    if rec.claimed_by_key_id != key.id:
        raise HTTPException(
            status_code=403,
            detail=f"这条任务由 {rec.claimed_by or '其他人'} 领取，只有领取者能操作",
        )


# ---------- 转换 ----------


def claim(db: Session, rec: ExecutionRecord, key: ApiKey) -> None:
    _require_current(rec)
    if rec.status == "in_progress":
        raise HTTPException(status_code=409, detail=f"已被 {rec.claimed_by} 领取，进行中")
    _require_status(rec, CLAIMABLE, "领取")
    retry = rec.status != "pending"
    rec.claimed_by = key.hint
    rec.claimed_by_key_id = key.id
    rec.implemented_by_key_id = None
    rec.results_json = "[]"
    rec.verification_json = "[]"
    rec.reason = ""  # 上一次 blocked / failed 的原因留在事件历史里，不再挂在当前状态上
    _transition(db, rec, "claim", "in_progress", key.hint,
                "重新领取" if retry else "", {"retry_from": rec.status} if retry else None)


def release(db: Session, rec: ExecutionRecord, key: ApiKey, force: bool) -> None:
    _require_status(rec, ("in_progress",), "释放")
    if not force:
        _require_holder(rec, key)
    rec.claimed_by = ""
    rec.claimed_by_key_id = None
    _transition(db, rec, "release", "pending", key.hint, "释放领取")


def report_blocked(db: Session, rec: ExecutionRecord, key: ApiKey, reason: str) -> None:
    _require_current(rec)
    _require_status(rec, ("in_progress",), "报告阻塞")
    _require_holder(rec, key)
    if not reason.strip():
        raise HTTPException(status_code=422, detail="必须写明阻塞原因（卡在哪个业务问题上）")
    rec.reason = reason.strip()
    _transition(db, rec, "blocked", "blocked", key.hint, rec.reason)


def report_failed(db: Session, rec: ExecutionRecord, key: ApiKey, reason: str) -> None:
    _require_current(rec)
    _require_status(rec, ("in_progress",), "报告失败")
    _require_holder(rec, key)
    if not reason.strip():
        raise HTTPException(status_code=422, detail="必须写明失败原因")
    rec.reason = reason.strip()
    _transition(db, rec, "failed", "failed", key.hint, rec.reason)


def _check_results(acceptance: list[dict], results: list[dict], who: str) -> list[dict]:
    """逐条验收条件的结果必须齐全且格式正确（不管通过与否）。返回规范化后的列表。"""
    ids = [a["id"] for a in acceptance]
    problems: list[str] = []
    clean: dict[str, dict] = {}
    for i, r in enumerate(results):
        ac_id = str(r.get("ac_id", "")).strip()
        result = str(r.get("result", "")).strip()
        evidence = str(r.get("evidence", "")).strip()
        if ac_id not in ids:
            problems.append(f"第 {i + 1} 条的 ac_id {ac_id!r} 不是该版本的验收条件")
            continue
        if ac_id in clean:
            problems.append(f"{ac_id} 重复出现")
            continue
        if result not in ("pass", "fail"):
            problems.append(f"{ac_id} 的 result 必须是 pass 或 fail")
            continue
        if not evidence:
            problems.append(f"{ac_id} 缺少 evidence（证据：测试输出、接口返回、观察到的现象等）")
            continue
        clean[ac_id] = {"ac_id": ac_id, "result": result, "evidence": evidence}
    missing = [i for i in ids if i not in clean and not any(i in p for p in problems)]
    if missing:
        problems.append(f"{who}必须逐条给出结果，缺少：{'、'.join(missing)}")
    if problems:
        raise HTTPException(status_code=422, detail={"error": "验收条件结果不完整", "problems": problems})
    return [clean[i] for i in ids]


def submit_implementation(
    db: Session, rec: ExecutionRecord, key: ApiKey, results: list[dict], note: str
) -> None:
    _require_current(rec)
    _require_status(rec, ("in_progress",), "提交实现结果")
    _require_holder(rec, key)
    checked = _check_results(version_acceptance(db, rec), results, "实现方")
    failing = [r["ac_id"] for r in checked if r["result"] != "pass"]
    if failing:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"还有验收条件没通过（{'、'.join(failing)}）：做完再提交；做不下去请用 report_failed / report_blocked",
                "failing": failing,
            },
        )
    rec.results_json = json.dumps(checked, ensure_ascii=False)
    rec.implemented_by_key_id = key.id
    _transition(db, rec, "implemented", "implemented", key.hint, note, {"results": checked})


def verify(db: Session, rec: ExecutionRecord, key: ApiKey, results: list[dict], note: str) -> str:
    """独立验收。全部通过 → verified；有不通过 → failed（原因写进记录）。返回新状态。"""
    _require_current(rec)
    _require_status(rec, ("implemented",), "验收")
    if rec.implemented_by_key_id == key.id:
        raise HTTPException(
            status_code=403,
            detail="验证者不能是实现者本人（同一把 key）：请换测试 Agent 的 key 验收",
        )
    checked = _check_results(version_acceptance(db, rec), results, "验证方")
    rec.verification_json = json.dumps(checked, ensure_ascii=False)
    failing = [r for r in checked if r["result"] != "pass"]
    if not failing:
        _transition(db, rec, "verified", "verified", key.hint, note, {"results": checked})
        return "verified"
    rec.reason = "验收不通过：" + "；".join(f"{r['ac_id']}（{r['evidence']}）" for r in failing)
    _transition(db, rec, "verify_failed", "failed", key.hint, rec.reason, {"results": checked})
    return "failed"
