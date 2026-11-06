"""执行接口：待办列表、领取（拿到锁定版本的完整上下文）、报告进展、提交实现结果、独立验收。

状态机与校验在 ``executions.py``；这里只做鉴权（exec.read / exec.write / exec.verify）、
项目隔离和序列化。规格内容在这里是只读的。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from speclock import executions
from speclock import permissions as perms
from speclock.api_agent import _block_out, _check_project_scope
from speclock.db import get_db
from speclock.engine import published_version
from speclock.models import ApiKey, Block, ExecutionRecord
from speclock.permissions import require_permission
from speclock.schemas import WorkReason, WorkResults

router = APIRouter(prefix="/api/v1", tags=["execution"])


def _record(db: Session, work_id: int, key: ApiKey) -> ExecutionRecord:
    rec = db.get(ExecutionRecord, work_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"work {work_id} not found")
    _check_project_scope(key, rec.block.capability.business.project_id)
    return rec


def _summary(rec: ExecutionRecord) -> dict:
    block = rec.block
    cap = block.capability
    return {
        "id": rec.id,
        "block_id": block.id,
        "block_title": block.title,
        "capability_id": cap.id,
        "capability_title": cap.title,
        "business": cap.business.name,
        "version": rec.version,
        "status": rec.status,
        "claimed_by": rec.claimed_by,
        "reason": rec.reason,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


def _detail(db: Session, rec: ExecutionRecord) -> dict:
    """记录 + 事件历史 + 锁定到该版本的完整规格（领取后按这份干活，不会因后续发布而变）。"""
    bv = published_version(db, rec.block, rec.version)
    return {
        **_summary(rec),
        "implementation": json.loads(rec.results_json or "[]"),
        "verification": json.loads(rec.verification_json or "[]"),
        "events": [
            {
                "event": e.event,
                "from": e.from_status,
                "to": e.to_status,
                "actor": e.actor,
                "note": e.note,
                "detail": json.loads(e.detail_json or "{}"),
                "created_at": e.created_at,
            }
            for e in rec.events
        ],
        "spec": _block_out(bv, rec).model_dump(mode="json"),
    }


@router.get("/work")
def list_work(
    status: str | None = Query(default=None, description="按状态筛选；缺省 = 除已被取代外的全部"),
    block_id: int | None = None,
    capability_id: int | None = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.read")),
):
    """待办 / 执行记录列表（新的在前）。只含已发布模块的记录。
    例：``status=pending`` 是待领取队列，``status=implemented`` 是待验收队列，
    ``status=blocked`` 是等业务答复的项。``mine=true`` 只看自己领取过的。"""
    if status is not None and status not in executions.ALL_STATUSES:
        raise HTTPException(status_code=422, detail=f"status 必须是：{'、'.join(executions.ALL_STATUSES)}")
    q = db.query(ExecutionRecord).join(Block, Block.id == ExecutionRecord.block_id)
    q = q.filter(Block.status == "published")
    if status:
        q = q.filter(ExecutionRecord.status == status)
    else:
        q = q.filter(ExecutionRecord.status != "superseded")
    if block_id is not None:
        q = q.filter(ExecutionRecord.block_id == block_id)
    if capability_id is not None:
        q = q.filter(Block.capability_id == capability_id)
    if mine:
        q = q.filter(ExecutionRecord.claimed_by_key_id == key.id)
    out = []
    for rec in q.order_by(ExecutionRecord.id.desc()).all():
        if key.project_id is not None and rec.block.capability.business.project_id != key.project_id:
            continue
        out.append(_summary(rec))
    return out


@router.get("/work/{work_id}")
def get_work(
    work_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.read")),
):
    return _detail(db, _record(db, work_id, key))


@router.post("/work/{work_id}/claim")
def claim_work(
    work_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.write")),
):
    """领取：pending / failed / blocked → in_progress。返回锁定到该版本的完整规格。"""
    rec = _record(db, work_id, key)
    executions.claim(db, rec, key)
    db.commit()
    return _detail(db, rec)


@router.post("/work/{work_id}/release")
def release_work(
    work_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.write")),
):
    """放弃领取：in_progress → pending。领取者本人，或拥有 key.manage 的管理员。"""
    rec = _record(db, work_id, key)
    force = "key.manage" in perms.role_permissions(key.role)
    executions.release(db, rec, key, force)
    db.commit()
    return _summary(rec)


@router.post("/work/{work_id}/blocked")
def blocked_work(
    work_id: int,
    body: WorkReason,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.write")),
):
    """业务上卡住（规格缺信息 / 互相矛盾）：in_progress → blocked，附原因。"""
    rec = _record(db, work_id, key)
    executions.report_blocked(db, rec, key, body.reason)
    db.commit()
    return _summary(rec)


@router.post("/work/{work_id}/failed")
def failed_work(
    work_id: int,
    body: WorkReason,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.write")),
):
    """执行失败：in_progress → failed，附原因；之后可以重新领取。"""
    rec = _record(db, work_id, key)
    executions.report_failed(db, rec, key, body.reason)
    db.commit()
    return _summary(rec)


@router.post("/work/{work_id}/implementation")
def submit_implementation(
    work_id: int,
    body: WorkResults,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.write")),
):
    """提交实现结果：逐条验收条件自测（pass + 证据），全部通过 → implemented。"""
    rec = _record(db, work_id, key)
    executions.submit_implementation(
        db, rec, key, [r.model_dump() for r in body.results], body.note
    )
    db.commit()
    return _summary(rec)


@router.post("/work/{work_id}/verification")
def verify_work(
    work_id: int,
    body: WorkResults,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("exec.verify")),
):
    """独立验收：逐条验收条件给出结果。全通过 → verified；有不通过 → failed。
    验证者不能是实现者（同一把 key）。"""
    rec = _record(db, work_id, key)
    executions.verify(db, rec, key, [r.model_dump() for r in body.results], body.note)
    db.commit()
    return _summary(rec)
