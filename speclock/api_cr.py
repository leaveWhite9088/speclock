"""审核单（Change Request）与 Commit 接口。

这是规格库**唯一**的写入通道，由权限而非 key 前缀放行：

- 需求 Agent（``cr.write`` / ``commit.write``）：整理审核单 → 提交 → 等人批准 →
  在已批准的审核单下提交 Commit → 报告完成；
- 人（``cr.approve``，人类专属权限）：批准或驳回。agent 类角色挂不上这条权限，所以
  Agent 永远批准不了任何审核单。

状态：draft → pending_review → approved → applied；pending_review → rejected；
approved → superseded。提交起内容冻结（想改先撤回成 draft），批准时必须带上审核单
内容哈希——批准的就是人看到的那一版。
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from speclock import diffing
from speclock.auth import audit
from speclock.commits import apply_commit
from speclock.db import get_db
from speclock.models import ApiKey, ChangeRequest, Commit, Project, utcnow
from speclock import permissions as perms
from speclock.permissions import require_permission
from speclock.schemas import CRApprove, CRCreate, CRReject, CRUpdate, CommitCreate

router = APIRouter(prefix="/api/v1", tags=["change-requests"])

STATUSES = ("draft", "pending_review", "approved", "applied", "rejected", "superseded")


def content_hash(cr: ChangeRequest) -> str:
    """审核单业务内容的哈希（提交时冻结）。不含状态 / 时间等流转字段。"""
    payload = {
        "project_id": cr.project_id,
        "title": cr.title,
        "intent": cr.intent,
        "expected_outcome": cr.expected_outcome,
        "obsolete": json.loads(cr.obsolete_json or "[]"),
        "acceptance": json.loads(cr.acceptance_json or "[]"),
        "impact_note": cr.impact_note,
        "supersedes_id": cr.supersedes_id,
        "kind": cr.kind,
        "kind_reason": cr.kind_reason,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _check_project(key: ApiKey, project_id: int) -> None:
    """项目隔离：绑定了项目的 key 只能访问本项目的审核单；跨项目一律 404。"""
    if key.project_id is not None and key.project_id != project_id:
        raise HTTPException(status_code=404, detail="change request not found")


def _get_cr(db: Session, key: ApiKey, cr_id: int) -> ChangeRequest:
    cr = db.get(ChangeRequest, cr_id)
    if cr is None:
        raise HTTPException(status_code=404, detail="change request not found")
    _check_project(key, cr.project_id)
    return cr


def _covered(cr: ChangeRequest) -> set[str]:
    out: set[str] = set()
    for c in cr.commits:
        out.update(json.loads(c.covers_json or "[]"))
    return out


def _commit_out(c: Commit) -> dict:
    return {
        "id": c.id,
        "seq": c.seq,
        "covers": json.loads(c.covers_json or "[]"),
        "change_note": c.change_note,
        "ops": json.loads(c.ops_json or "[]"),
        "result": json.loads(c.result_json or "{}"),
        "created_by": c.created_by,
        "created_at": c.created_at,
    }


def cr_out(cr: ChangeRequest, detail: bool = True) -> dict:
    acceptance = json.loads(cr.acceptance_json or "[]")
    covered = _covered(cr)
    out = {
        "id": cr.id,
        "project_id": cr.project_id,
        "title": cr.title,
        "intent": cr.intent,
        "expected_outcome": cr.expected_outcome,
        "obsolete": json.loads(cr.obsolete_json or "[]"),
        "acceptance": acceptance,
        "impact_note": cr.impact_note,
        "kind": cr.kind,
        "kind_reason": cr.kind_reason,
        "status": cr.status,
        "content_hash": cr.content_hash,
        "supersedes_id": cr.supersedes_id,
        "superseded_by_id": cr.superseded_by_id,
        "created_by": cr.created_by,
        "created_at": cr.created_at,
        "submitted_at": cr.submitted_at,
        "decided_by": cr.decided_by,
        "decided_at": cr.decided_at,
        "decision_via": cr.decision_via,
        "decision_evidence": cr.decision_evidence,
        "decision_note": cr.decision_note,
        "applied_at": cr.applied_at,
        "commit_count": len(cr.commits),
        "coverage": {
            "covered": [a["id"] for a in acceptance if a["id"] in covered],
            "missing": [a["id"] for a in acceptance if a["id"] not in covered],
        },
    }
    if detail:
        out["commits"] = [_commit_out(c) for c in cr.commits]
    return out


def _clean_obsolete(raw: list[str]) -> list[str]:
    out = []
    for s in raw:
        if not isinstance(s, str) or not s.strip():
            raise HTTPException(status_code=422, detail="obsolete 的每一项必须是非空字符串")
        out.append(s.strip())
    return out


def _clean_acceptance(raw: list) -> list[dict]:
    try:
        items = diffing.validate_acceptance([e.model_dump() for e in raw])
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"验收条件清单不合法: {exc}") from exc
    return diffing.assign_item_ids(items, "acceptance")


def _check_supersedes(db: Session, project_id: int, supersedes_id: int | None, self_id: int | None):
    if supersedes_id is None:
        return
    old = db.get(ChangeRequest, supersedes_id)
    if old is None or old.project_id != project_id or old.id == self_id:
        raise HTTPException(status_code=422, detail=f"supersedes_id {supersedes_id} 不是本项目的其他审核单")
    if old.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"只能取代已批准但未完成的审核单，#{old.id} 当前是 {old.status}",
        )


def _require_internal_permission(key: ApiKey) -> None:
    if "cr.internal" not in perms.role_permissions(key.role):
        raise HTTPException(
            status_code=403,
            detail="当前密钥的角色缺少权限：cr.internal（开「内部整理」类审核单需要）",
        )


def _require_owner(cr: ChangeRequest, key: ApiKey) -> None:
    """草稿只有开单的那把 key（或拥有 key.manage 的管理员）能改、撤回、提交，
    避免多个 Agent 同时有 cr.write 时误改别人的草稿。"""
    if cr.created_by == key.hint:
        return
    if "key.manage" in perms.role_permissions(key.role):
        return
    raise HTTPException(
        status_code=403,
        detail=f"这张审核单是 {cr.created_by} 开的，只有它（或管理员）能修改、提交或撤回",
    )


def _require_status(cr: ChangeRequest, *allowed: str) -> None:
    if cr.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"审核单是 {cr.status}，该操作只允许在 {' / '.join(allowed)} 状态下进行",
        )


# ---------- 创建 / 读取 / 编辑草稿 ----------


@router.post("/change-requests", status_code=201)
def create_cr(
    body: CRCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.write")),
):
    project_id = body.project_id if body.project_id is not None else key.project_id
    if project_id is None:
        raise HTTPException(status_code=422, detail="project_id 必填（全局 key 必须指明项目）")
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    _check_project(key, project_id)
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title 不能为空")
    _check_supersedes(db, project_id, body.supersedes_id, None)
    if body.kind == "internal":
        _require_internal_permission(key)
    cr = ChangeRequest(
        project_id=project_id,
        title=body.title.strip(),
        intent=body.intent,
        expected_outcome=body.expected_outcome,
        obsolete_json=json.dumps(_clean_obsolete(body.obsolete), ensure_ascii=False),
        acceptance_json=json.dumps(_clean_acceptance(body.acceptance), ensure_ascii=False),
        impact_note=body.impact_note,
        supersedes_id=body.supersedes_id,
        kind=body.kind,
        kind_reason=body.kind_reason.strip(),
        created_by=key.hint,
    )
    db.add(cr)
    db.flush()
    audit(db, key.hint, "cr_create", f"cr:{cr.id}", {"title": cr.title})
    db.commit()
    return cr_out(cr)


@router.get("/change-requests")
def list_crs(
    status: str | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.read")),
):
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status 必须是 {STATUSES} 之一")
    q = db.query(ChangeRequest)
    if key.project_id is not None:
        q = q.filter(ChangeRequest.project_id == key.project_id)
    if project_id is not None:
        q = q.filter(ChangeRequest.project_id == project_id)
    if status:
        q = q.filter(ChangeRequest.status == status)
    return [cr_out(cr, detail=False) for cr in q.order_by(ChangeRequest.id.desc()).all()]


@router.get("/change-requests/{cr_id}")
def get_cr(
    cr_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.read")),
):
    return cr_out(_get_cr(db, key, cr_id))


@router.put("/change-requests/{cr_id}")
def update_cr(
    cr_id: int,
    body: CRUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.write")),
):
    cr = _get_cr(db, key, cr_id)
    _require_owner(cr, key)
    _require_status(cr, "draft")  # 提交起内容冻结；想改先撤回
    changed: list[str] = []
    for field in ("title", "intent", "expected_outcome", "impact_note"):
        value = getattr(body, field)
        if value is not None:
            if field == "title" and not value.strip():
                raise HTTPException(status_code=422, detail="title 不能为空")
            setattr(cr, field, value.strip() if field == "title" else value)
            changed.append(field)
    if body.obsolete is not None:
        cr.obsolete_json = json.dumps(_clean_obsolete(body.obsolete), ensure_ascii=False)
        changed.append("obsolete")
    if body.acceptance is not None:
        cr.acceptance_json = json.dumps(_clean_acceptance(body.acceptance), ensure_ascii=False)
        changed.append("acceptance")
    if body.supersedes_id is not None:
        _check_supersedes(db, cr.project_id, body.supersedes_id, cr.id)
        cr.supersedes_id = body.supersedes_id
        changed.append("supersedes_id")
    if body.kind is not None:
        if body.kind == "internal":
            _require_internal_permission(key)
        cr.kind = body.kind
        changed.append("kind")
    if body.kind_reason is not None:
        cr.kind_reason = body.kind_reason.strip()
        changed.append("kind_reason")
    audit(db, key.hint, "cr_update", f"cr:{cr.id}", {"fields": changed})
    db.commit()
    return cr_out(cr)


# ---------- 提交 / 撤回 ----------


@router.post("/change-requests/{cr_id}/submit")
def submit_cr(
    cr_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.write")),
):
    cr = _get_cr(db, key, cr_id)
    _require_owner(cr, key)
    _require_status(cr, "draft")
    missing = []
    if not cr.intent.strip():
        missing.append("intent（为什么变）不能为空")
    if not cr.expected_outcome.strip():
        missing.append("expected_outcome（变成什么样）不能为空")
    if not json.loads(cr.acceptance_json or "[]"):
        missing.append("acceptance（验收条件）至少 1 条")
    if missing:
        raise HTTPException(
            status_code=422, detail={"error": "审核单不完整，不能提交", "missing": missing}
        )
    if cr.kind == "internal":
        _require_internal_permission(key)
        if not cr.kind_reason.strip():
            raise HTTPException(
                status_code=422,
                detail={"error": "审核单不完整，不能提交",
                        "missing": ["内部整理必须在 kind_reason 里写明：为什么这不算业务变更"]},
            )
        if cr.supersedes_id is not None:
            raise HTTPException(status_code=422, detail="内部整理不能取代其他审核单")
    _check_supersedes(db, cr.project_id, cr.supersedes_id, cr.id)
    cr.status = "pending_review"
    cr.submitted_at = utcnow()
    cr.content_hash = content_hash(cr)
    audit(db, key.hint, "cr_submit", f"cr:{cr.id}", {"content_hash": cr.content_hash})
    if cr.kind == "internal":
        # 内部整理：Agent 自行判定，提交即生效，不经人批准；留痕并在 Commit 时由 Core
        # 机械检查「规则 / 验收条件 / API 的条目总和不变」
        cr.status = "approved"
        cr.decided_by = key.hint
        cr.decided_at = utcnow()
        cr.decision_via = "agent_declared"
        cr.decision_evidence = cr.kind_reason
        cr.decision_note = "内部整理：由 Agent 自行判定不改变业务内容，未经人批准"
        audit(db, key.hint, "cr_approve", f"cr:{cr.id}",
              {"via": "agent_declared", "kind": "internal", "reason": cr.kind_reason,
               "content_hash": cr.content_hash})
    db.commit()
    return cr_out(cr)


@router.post("/change-requests/{cr_id}/withdraw")
def withdraw_cr(
    cr_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.write")),
):
    """撤回审核单回到草稿（内容解冻，之前的哈希作废）。

    - 待审核（pending_review）的都可以撤回；
    - **内部整理单**提交即生效（approved），但没有任何人的批准可言：如果它还没有任何 Commit
      落地（例如 Commit 被「条目总和变了」拦下，不想继续了），也可以撤回，免得留下一张
      永远停在 approved 的空单。人批准过的审核单不能这样撤回（批准后不可修改）。"""
    cr = _get_cr(db, key, cr_id)
    _require_owner(cr, key)
    stranded_internal = cr.status == "approved" and cr.kind == "internal" and not cr.commits
    if not stranded_internal:
        _require_status(cr, "pending_review")
    cr.status = "draft"
    cr.submitted_at = None
    cr.content_hash = ""
    if stranded_internal:
        cr.decided_by = ""
        cr.decided_at = None
        cr.decision_via = ""
        cr.decision_evidence = ""
        cr.decision_note = ""
    audit(db, key.hint, "cr_withdraw", f"cr:{cr.id}",
          {"was": "approved_internal_without_commits"} if stranded_internal else {})
    db.commit()
    return cr_out(cr)


# ---------- 人的决定：批准 / 驳回（cr.approve 是人类专属权限） ----------


def _check_evidence(via: str, evidence: str) -> None:
    if via == "natural_language" and not evidence.strip():
        raise HTTPException(
            status_code=422, detail="via=natural_language 必须在 evidence 里留下人的原话"
        )


@router.post("/change-requests/{cr_id}/approve")
def approve_cr(
    cr_id: int,
    body: CRApprove,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.approve")),
):
    cr = _get_cr(db, key, cr_id)
    _require_status(cr, "pending_review")
    if body.content_hash != cr.content_hash:
        raise HTTPException(
            status_code=409,
            detail="审核单内容已变化（撤回并重新提交过），请重新查看后再批准",
        )
    _check_evidence(body.via, body.evidence)
    if cr.supersedes_id is not None:
        old = db.get(ChangeRequest, cr.supersedes_id)
        if old is None or old.status != "approved":
            raise HTTPException(
                status_code=409,
                detail=f"要取代的审核单 #{cr.supersedes_id} 已不是 approved（{old.status if old else '不存在'}）",
            )
        old.status = "superseded"
        old.superseded_by_id = cr.id
        audit(db, key.hint, "cr_superseded", f"cr:{old.id}", {"by": cr.id})
    cr.status = "approved"
    cr.decided_by = key.hint
    cr.decided_at = utcnow()
    cr.decision_via = body.via
    cr.decision_evidence = body.evidence
    cr.decision_note = body.note
    audit(
        db, key.hint, "cr_approve", f"cr:{cr.id}",
        {"via": body.via, "content_hash": cr.content_hash, "evidence": body.evidence},
    )
    db.commit()
    return cr_out(cr)


@router.post("/change-requests/{cr_id}/reject")
def reject_cr(
    cr_id: int,
    body: CRReject,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("cr.approve")),
):
    cr = _get_cr(db, key, cr_id)
    _require_status(cr, "pending_review")
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="驳回必须填写理由 reason")
    _check_evidence(body.via, body.evidence)
    cr.status = "rejected"
    cr.decided_by = key.hint
    cr.decided_at = utcnow()
    cr.decision_via = body.via
    cr.decision_evidence = body.evidence
    cr.decision_note = body.reason.strip()
    audit(db, key.hint, "cr_reject", f"cr:{cr.id}",
          {"via": body.via, "reason": cr.decision_note, "evidence": body.evidence})
    db.commit()
    return cr_out(cr)


# ---------- Commit / 完成 ----------


@router.post("/change-requests/{cr_id}/commits")
def create_commit(
    cr_id: int,
    body: CommitCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("commit.write")),
):
    """在已批准的审核单下提交一个 Commit：ops 原子应用并发布，任何一条失败整体回滚。
    dryRun=true 完整执行后回滚，返回会得到的结果（不落库、不写审计）。"""
    cr = _get_cr(db, key, cr_id)
    commit, outcome = apply_commit(
        db, cr, body.ops, body.covers, body.change_note, actor=key.hint, dry_run=body.dryRun
    )
    if body.dryRun:
        return {"dry_run": True, "cr_id": cr_id, **outcome}
    return {"dry_run": False, "cr_id": cr_id, "commit_id": commit.id, "seq": commit.seq,
            "covers": json.loads(commit.covers_json), **outcome}


@router.post("/change-requests/{cr_id}/complete")
def complete_cr(
    cr_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("commit.write")),
):
    """需求 Agent 报告「这个审核单要求的变更都已落进规格库」。Core 做机械的覆盖检查：
    审核单的每条验收条件都必须被至少一个 Commit 声明覆盖，否则 409 并指出缺哪几条。
    （声明是否属实由后续验证环节负责，不由 Core 判断。）"""
    cr = _get_cr(db, key, cr_id)
    _require_status(cr, "approved")
    if not cr.commits:
        raise HTTPException(status_code=409, detail="还没有任何 Commit，不能标记完成")
    covered = _covered(cr)
    missing = [a["id"] for a in json.loads(cr.acceptance_json or "[]") if a["id"] not in covered]
    if missing:
        raise HTTPException(
            status_code=409,
            detail={"error": "仍有验收条件没有被任何 Commit 覆盖", "missing": missing},
        )
    cr.status = "applied"
    cr.applied_at = utcnow()
    audit(db, key.hint, "cr_applied", f"cr:{cr.id}", {"commits": len(cr.commits)})
    db.commit()
    return cr_out(cr)
