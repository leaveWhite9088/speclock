"""管理 API：读视图（SPA 用）+ 项目 / 密钥 / 角色管理。

**这里没有任何改写规格内容的接口**：模块、小业务、大业务的创建 / 修改 / 发布 / 归档
只能通过审核单下的 Commit（见 ``api_cr.py`` / ``commits.py``）完成。每个接口按权限放行
（``permissions.require_permission``），不再按 key 前缀。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, not_, or_
from sqlalchemy.orm import Session

from speclock_config import keyfiles
from speclock_core import permissions as perms
from speclock_server.scope import check_project_scope
from speclock_core import audit, hash_key, key_hint, new_key
from speclock_core import get_db
from speclock_core import published_version
from speclock_config import find_home, mcp_config
from speclock_core import executions
from speclock_core import ApiKey, AuditLog, Block, BlockVersion, Business, Capability, CapabilityVersion, ChangeRequest, Commit, ExecutionEvent, ExecutionRecord, Project, Role, utcnow
from speclock_server.deps import require_key, require_permission
from speclock_server.responses import (
    ActivityOut, ArchivedBlockOut, BlockVersionEntry, BlockVersionFull, CapabilityVersionEntry,
    DeletedOut, KeyCreatedOut, KeyListEntry, MeOut, PermissionOut, ProjectDeletedOut, ProjectOut,
    RoleOut, TreeProject,
)
from speclock_core import ApiError, KeyCreate, ensure_web_key, ProjectCreate, RenameRequest, RoleCreate, RoleUpdate

router = APIRouter(prefix="/api/v1", tags=["admin"])

ROLE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")


def _get_block(db: Session, block_id: int) -> Block:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    return block


# ---------- 当前 key 是谁 ----------


@router.get("/me", response_model=MeOut)
def whoami(key: ApiKey = Depends(require_key)):
    """当前 key 的身份与权限（MCP 客户端据此只暴露有权限的工具）。"""
    return {
        "key_id": key.id,
        "hint": key.hint,
        "kind": key.prefix,
        "label": key.label,
        "project_id": key.project_id,
        "role": key.role.name if key.role else None,
        "surface": key.surface or "",
        "permissions": sorted(perms.role_permissions(key.role)),
    }


# ---------- SPA read endpoints（读操作不写审计） ----------


def _tree_exec(recs: list[ExecutionRecord]) -> dict:
    ex = executions.exec_fields(recs)
    return {"execution_status": ex["execution_status"], "works": ex["works"]}


@router.get("/tree", response_model=list[TreeProject])
def get_tree(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))
):
    """全量聚合树：projects → businesses → capabilities → blocks，供 SPA 文档树主页
    一次拉取。含全部状态（draft / published / archived）的模块。"""
    published_at_map = {
        (bv.block_id, bv.version): bv.published_at
        for bv in db.query(BlockVersion).all()
    }
    exec_recs: dict[tuple[int, str], list[ExecutionRecord]] = {}
    for r in db.query(ExecutionRecord).order_by(ExecutionRecord.id).all():
        exec_recs.setdefault((r.block_id, r.version), []).append(r)
    return [
        {
            "id": p.id,
            "name": p.name,
            "businesses": [
                {
                    "id": d.id,
                    "name": d.name,
                    "capabilities": [
                        {
                            "id": doc.id,
                            "title": doc.title,
                            "summary": doc.summary,
                            "current_version": doc.current_version,
                            "blocks": [
                                {
                                    "id": b.id,
                                    "title": b.title,
                                    "status": b.status,
                                    "current_published_version": b.current_published_version,
                                    "current_published_at": published_at_map.get(
                                        (b.id, b.current_published_version)
                                    ),
                                    **_tree_exec(exec_recs.get((b.id, b.current_published_version), [])),
                                }
                                for b in doc.blocks
                            ],
                        }
                        for doc in d.capabilities
                    ],
                }
                for d in p.businesses
            ],
        }
        for p in db.query(Project).order_by(Project.id).all()
        if key.project_id is None or key.project_id == p.id
    ]


@router.get("/archive", response_model=list[ArchivedBlockOut])
def list_archive(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))
):
    """已归档模块列表（含所属小业务 / 大业务 / 项目名称），对应 UI 归档页。"""
    return [
        {
            "id": b.id,
            "title": b.title,
            "current_published_version": b.current_published_version,
            "archived_at": b.archived_at,
            "capability_id": b.capability_id,
            "capability_title": b.capability.title,
            "business_id": b.capability.business_id,
            "business_name": b.capability.business.name,
            "project_id": b.capability.business.project_id,
            "project_name": b.capability.business.project.name,
        }
        for b in db.query(Block)
        .filter(Block.status == "archived")
        .order_by(Block.id)
        .all()
        if key.project_id is None or key.project_id == b.capability.business.project_id
    ]


def _action_clause(spec: str):
    """逗号分隔的动作列表；以 * 结尾的是前缀（``cr_*``），其余精确匹配。返回 OR 条件。"""
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise HTTPException(status_code=422, detail="action 不能为空")
    clauses = [
        AuditLog.action.like(p[:-1].replace("%", "") + "%") if p.endswith("*") else AuditLog.action == p
        for p in parts
    ]
    return or_(*clauses)


def _parse_time(name: str, value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} 不是合法的时间（ISO 格式）") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)  # 库里存的是 UTC 无时区
    return dt


@router.get("/activity", response_model=list[ActivityOut])
def list_activity(
    limit: int = Query(default=50, ge=1, le=500),
    actor_prefix: str | None = None,
    actor: str | None = Query(default=None, description="按 key 的 hint 精确过滤"),
    action: str | None = Query(default=None, description="只看这些动作，逗号分隔，以 * 结尾为前缀，如 cr_*,commit"),
    exclude_action: str | None = Query(default=None, description="排除这些动作，写法同 action，如 pull"),
    target_prefix: str | None = Query(default=None, description="对象前缀，如 block:3 或 cr:5"),
    since: str | None = Query(default=None, description="起始时间（含），ISO 格式"),
    until: str | None = Query(default=None, description="截止时间（不含），ISO 格式"),
    before_id: int | None = Query(default=None, description="游标：只取 id 小于它的（加载更多）"),
    after_id: int | None = Query(default=None, description="游标：只取 id 大于它的（取某个 id 之后的新事件）"),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("audit.read")),
):
    """审计日志（新的在前，按 id 倒序）。所有筛选条件可以组合；翻页用 ``before_id``
    （传上一页最后一条的 id）；取新事件用 ``after_id``（传已处理到的最大 id），排序仍是新的在前。
    ``after_id`` 之后的事件多于 ``limit`` 时返回的是**最新**的 ``limit`` 条，中间缺的一段用
    ``before_id=本页最小 id`` 往回补，直到补到 ``after_id``。actor_prefix 可按 key 前缀过滤（如 ``agent`` 只看 AI 活动）。"""
    q = db.query(AuditLog)
    if key.project_id is not None and not _is_super(key):
        q = q.filter(AuditLog.project_id == key.project_id)  # 项目绑定的 key 只看得到本项目的活动
    if actor_prefix:
        q = q.filter(AuditLog.actor.like(f"{actor_prefix}%"))
    if actor:
        q = q.filter(AuditLog.actor == actor)
    if action:
        q = q.filter(_action_clause(action))
    if exclude_action:
        q = q.filter(not_(_action_clause(exclude_action)))
    if target_prefix:
        q = q.filter(AuditLog.target.like(target_prefix.replace("%", "") + "%"))
    if since:
        q = q.filter(AuditLog.created_at >= _parse_time("since", since))
    if until:
        q = q.filter(AuditLog.created_at < _parse_time("until", until))
    if before_id is not None:
        q = q.filter(AuditLog.id < before_id)
    if after_id is not None:
        q = q.filter(AuditLog.id > after_id)
    return [
        {
            "id": a.id,
            "actor": a.actor,
            "action": a.action,
            "target": a.target,
            "detail": json.loads(a.detail_json or "{}"),
            "created_at": a.created_at,
        }
        for a in q.order_by(AuditLog.id.desc()).limit(limit).all()
    ]


# ---------- projects ----------


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))
):
    return [
        {"id": p.id, "name": p.name}
        for p in db.query(Project).order_by(Project.id).all()
        if key.project_id is None or key.project_id == p.id
    ]


@router.post("/projects", status_code=201, response_model=ProjectOut)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("project.manage")),
):
    p = Project(name=body.name)
    db.add(p)
    db.flush()
    audit(db, key.hint, "project_create", f"project:{body.name}", {}, project_id=p.id)
    db.commit()
    ensure_web_key(p.id)  # 这个项目的网页只读 key（普通的 viewer key，存成 key 文件）：新项目立刻有网页可看
    return {"id": p.id, "name": p.name}


@router.put("/projects/{project_id}", response_model=ProjectOut)
def rename_project(
    project_id: int,
    body: RenameRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("project.manage")),
):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
    p.name = body.name
    audit(db, key.hint, "rename", f"project:{p.id}", {"name": body.name})
    db.commit()
    return {"id": p.id, "name": p.name}


def _hard_delete_block(db: Session, block: Block) -> None:
    rec_ids = [r.id for r in db.query(ExecutionRecord).filter(ExecutionRecord.block_id == block.id)]
    if rec_ids:
        db.query(ExecutionEvent).filter(ExecutionEvent.record_id.in_(rec_ids)).delete(
            synchronize_session=False
        )
        db.query(ExecutionRecord).filter(ExecutionRecord.id.in_(rec_ids)).delete(
            synchronize_session=False
        )
    db.query(BlockVersion).filter(BlockVersion.block_id == block.id).delete()
    db.delete(block)


def _refuse_published(blocks: list[Block], message: str) -> None:
    published = [b for b in blocks if b.status == "published"]
    if published:
        raise ApiError("published_blocks_exist", {
            "error": message,
            "published_blocks": [{"id": b.id, "title": b.title} for b in published],
        })


def _hard_delete_capability(db: Session, doc: Capability) -> None:
    _refuse_published(doc.blocks, "小业务下仍有已发布模块，请先（通过审核单）归档这些模块再删除")
    for b in doc.blocks:
        _hard_delete_block(db, b)
    db.query(CapabilityVersion).filter(CapabilityVersion.capability_id == doc.id).delete()
    db.delete(doc)


def _count_admins(
    db: Session,
    exclude_key_ids: set[int] = frozenset(),
    role_override: dict[int, set[str]] | None = None,
) -> int:
    """假设做了某些变更后，还有多少把 human key 是超级管理员（key.manage + project.manage，防止把自己锁在门外；
    只管本项目的项目管理员不算）。"""
    n = 0
    for k in db.query(ApiKey).filter(ApiKey.prefix == "human").all():
        if k.id in exclude_key_ids or k.role is None:
            continue
        have = (role_override or {}).get(k.role_id)
        if have is None:
            have = perms.role_permissions(k.role)
        if {"key.manage", "project.manage"} <= have:
            n += 1
    return n


def _is_super(key: ApiKey) -> bool:
    """超级管理员：能管项目（project.manage）。其余有 key.manage 的是项目管理员，只能管自己项目的 key。"""
    return "project.manage" in perms.role_permissions(key.role)


def _require_super(key: ApiKey) -> None:
    if not _is_super(key):
        raise ApiError("super_admin_required", "这个操作只有超级管理员（admin）能做；项目管理员只管本项目的 key")


def _key_in_scope(key: ApiKey, k: ApiKey) -> bool:
    """项目管理员（绑定了项目、又不是超级管理员）只看得到、管得了本项目的 key。"""
    return _is_super(key) or key.project_id is None or k.project_id == key.project_id


_DELETE_CR = Query(description="授权这次删除的审核单：本项目里、人批准过的业务变更单，里面要点名要删的东西")


def _authorize_deletion(db: Session, cr_id: int, project_id: int, what: str, names: list[str]) -> ChangeRequest:
    """删除必须有人的同意：一张本项目里、**人批准过**的业务变更单（approved / applied，内部整理单不算），
    并且单子的内容（标题、意图、预期结果、影响说明、验收条件）里点名了要删的东西。
    和归档模块一样，授权来自审核单，而不是调用者自己说一句"人同意了"。"""
    cr = db.get(ChangeRequest, cr_id)
    if cr is None or cr.project_id != project_id:
        raise ApiError("delete_needs_approval",
                       f"删除{what}必须有一张本项目里、人批准过的业务变更单：先用 create_change_request 开单写明要删什么，等人批准，再带上它的 cr_id")
    if cr.kind != "business" or cr.status not in ("approved", "applied"):
        raise ApiError("delete_needs_approval",
                       f"审核单 {cr.id} 是 {cr.kind} / {cr.status}：删除必须由人批准过的业务变更单（approved 或 applied）授权")
    text = " ".join([cr.title, cr.intent, cr.expected_outcome, cr.impact_note, *json.loads(cr.obsolete_json or "[]"),
                     *(f"{a.get('name', '')} {a.get('detail', '')}" for a in json.loads(cr.acceptance_json or "[]"))])
    if not any(n and n in text for n in names):
        raise ApiError("delete_needs_approval",
                       f"审核单 {cr.id} 的内容里没有点名要删的{what}（{'、'.join(names)}）：人批准的是审核单里写的，不是别的")
    return cr


@router.delete("/blocks/{block_id}", response_model=DeletedOut)
def delete_block(
    block_id: int,
    cr_id: int = _DELETE_CR,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.delete")),
):
    """删除一个模块（连同它的全部版本和执行记录，不可恢复）。须有人批准过的业务变更单授权（``cr_id``，
    单子里点名这个模块）；已发布的模块要先通过审核单归档。"""
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="block not found")
    pid = block.capability.business.project_id
    check_project_scope(key, pid)
    cr = _authorize_deletion(db, cr_id, pid, "模块", [block.title])
    _refuse_published([block], "模块还是已发布状态，请先（通过审核单）归档它再删除")
    audit(db, key.hint, "delete", f"block:{block.id}",
          {"title": block.title, "cr_id": cr.id, "cr_title": cr.title}, project_id=pid)
    _hard_delete_block(db, block)
    db.commit()
    return {"id": block_id, "deleted": True}


@router.delete("/capabilities/{capability_id}", response_model=DeletedOut)
def delete_capability(
    capability_id: int,
    cr_id: int = _DELETE_CR,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.delete")),
):
    """删除一个小业务（连同它下面的模块、版本历史，不可恢复）。须有人批准过的业务变更单授权（单子里点名这个小业务）；
    其下有已发布模块时拒绝（409）。"""
    doc = db.get(Capability, capability_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="capability not found")
    pid = doc.business.project_id
    check_project_scope(key, pid)
    cr = _authorize_deletion(db, cr_id, pid, "小业务", [doc.title])
    audit(db, key.hint, "delete", f"capability:{doc.id}",
          {"title": doc.title, "blocks": len(doc.blocks), "cr_id": cr.id, "cr_title": cr.title}, project_id=pid)
    _hard_delete_capability(db, doc)
    db.commit()
    return {"id": capability_id, "deleted": True}


@router.delete("/businesses/{business_id}", response_model=DeletedOut)
def delete_business(
    business_id: int,
    cr_id: int = _DELETE_CR,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.delete")),
):
    """删除一个大业务（连同它下面的小业务、模块、版本历史，不可恢复）。须有人批准过的业务变更单授权（单子里点名这个大业务）；
    其下有已发布模块时拒绝（409）。"""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    check_project_scope(key, business.project_id)
    cr = _authorize_deletion(db, cr_id, business.project_id, "大业务", [business.name])
    audit(db, key.hint, "delete", f"business:{business.id}",
          {"name": business.name, "capabilities": len(business.capabilities), "cr_id": cr.id, "cr_title": cr.title},
          project_id=business.project_id)
    for doc in business.capabilities:
        _hard_delete_capability(db, doc)
    db.delete(business)
    db.commit()
    return {"id": business_id, "deleted": True}


@router.delete("/projects/{project_id}", response_model=ProjectDeletedOut)
def delete_project(
    project_id: int,
    cr_id: int = _DELETE_CR,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("project.manage")),
):
    """项目删除：须有该项目里人批准过的业务变更单授权（单子里点名这个项目），且其下无已发布模块（否则 409，先归档）。
    删除时级联硬删全部 大业务/小业务/模块/版本历史/审核单（授权它的那张也一并没了，审计里留着它的编号和标题），
    并一并删除绑定到该项目的 API key（避免遗留 key 失效语义不清）。"""
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
    cr = _authorize_deletion(db, cr_id, p.id, "项目", [p.name])
    bound_keys = db.query(ApiKey).filter(ApiKey.project_id == p.id).all()
    if _count_admins(db, {k.id for k in bound_keys}) < 1 and any(
        k.prefix == "human" for k in bound_keys
    ):
        raise HTTPException(
            status_code=409,
            detail="删除该项目会连带删除最后一把管理员 key，删除后无人能管理系统，已拒绝",
        )
    for business in p.businesses:
        for doc in business.capabilities:
            _hard_delete_capability(db, doc)  # raises 409 if any published module
        db.delete(business)
    cr_ids = [c.id for c in db.query(ChangeRequest).filter(ChangeRequest.project_id == p.id)]
    if cr_ids:
        db.query(Commit).filter(Commit.cr_id.in_(cr_ids)).delete(synchronize_session=False)
        db.query(ChangeRequest).filter(ChangeRequest.id.in_(cr_ids)).update(
            {"supersedes_id": None}, synchronize_session=False
        )
        db.query(ChangeRequest).filter(ChangeRequest.id.in_(cr_ids)).delete(
            synchronize_session=False
        )
    for k in bound_keys:
        db.delete(k)
    audit(db, key.hint, "delete", f"project:{p.id}",
          {"name": p.name, "deleted_keys": len(bound_keys), "deleted_crs": len(cr_ids),
           "cr_id": cr.id, "cr_title": cr.title}, project_id=p.id)
    db.delete(p)
    db.commit()
    return {"id": project_id, "deleted": True, "deleted_keys": len(bound_keys)}


# ---------- versions（读） ----------


def _trace(v) -> dict:
    return {"cr_id": v.cr_id, "commit_id": v.commit_id}


@router.get("/blocks/{block_id}/versions", response_model=list[BlockVersionEntry])
def list_versions(
    block_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """版本历史列表。每个版本附带该版本的执行记录（状态 + 事件历史）。"""
    block = _get_block(db, block_id)
    check_project_scope(key, block.capability.business.project_id)
    records: dict[str, list[ExecutionRecord]] = {}
    for r in (db.query(ExecutionRecord).filter(ExecutionRecord.block_id == block.id)
              .order_by(ExecutionRecord.id).all()):
        records.setdefault(r.version, []).append(r)
    current = block.current_published_version
    out = []
    for v in block.versions:
        recs = records.get(v.version, [])
        out.append(
            {
                "version": v.version,
                "level": v.level,
                "status": "current" if v.version == current else "deprecated",
                "superseded_by": None if v.version == current else current,
                "change_note": v.change_note,
                "delta": json.loads(v.delta_json),
                **_trace(v),
                "published_by": v.published_by,
                "published_at": v.published_at,
                **executions.exec_fields(recs),
                "surfaces": json.loads(v.surfaces_json or "[]"),
                "events": [
                    {
                        "event": e.event,
                        "from": e.from_status,
                        "to": e.to_status,
                        "actor": e.actor,
                        "note": e.note,
                        "created_at": e.created_at,
                        "surface": rec.surface,
                    }
                    for rec in recs
                    for e in rec.events
                ],
            }
        )
    return out


@router.get("/blocks/{block_id}/versions/{version}", response_model=BlockVersionFull)
def get_version(
    block_id: int,
    version: str,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """单个已发布版本的完整快照（human 侧，不限模块状态——已归档模块的历史
    版本同样可查）。对应 UI 的模块查看页。"""
    block = _get_block(db, block_id)
    bv = published_version(db, block, version)
    recs = executions.records_for(db, block.id, bv.version)
    return {
        "block_id": bv.block_id,
        "title": block.title,
        "status": block.status,
        "version": bv.version,
        "content_md": bv.content_md,
        "rules": json.loads(bv.rules_json or "[]"),
        "acceptance": json.loads(bv.acceptance_json or "[]"),
        "apis": json.loads(bv.apis_json or "[]"),
        "openapi_yaml": bv.openapi_yaml,
        "level": bv.level,
        "change_note": bv.change_note,
        "delta": json.loads(bv.delta_json),
        **_trace(bv),
        "published_by": bv.published_by,
        "published_at": bv.published_at,
        **executions.exec_fields(recs),
        "surfaces": json.loads(bv.surfaces_json or "[]"),
    }


@router.get("/capabilities/{capability_id}/versions", response_model=list[CapabilityVersionEntry])
def list_capability_versions(
    capability_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    doc = db.get(Capability, capability_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="capability not found")
    check_project_scope(key, doc.business.project_id)
    return [
        {
            "version": v.version,
            "status": "current" if v.version == doc.current_version else "deprecated",
            "superseded_by": None if v.version == doc.current_version else doc.current_version,
            "manifest": json.loads(v.manifest_json),
            "triggered_by_block_id": v.triggered_by_block_id,
            "change_note": v.change_note,
            **_trace(v),
            "published_by": v.published_by,
            "published_at": v.published_at,
        }
        for v in doc.versions
    ]


# ---------- 密钥与角色管理 ----------


def _key_out(k: ApiKey) -> dict:
    """列表视图：绝不含明文，也不含哈希，只给展示用 hint。"""
    return {
        "id": k.id,
        "hint": k.hint,
        "prefix": k.prefix,
        "role": k.role.name if k.role else None,
        "label": k.label,
        "key_file": k.key_file or "",
        "project_id": k.project_id,
        "surface": k.surface or "",
        "created_at": k.created_at,
    }


def _key_activity(db: Session) -> dict[str, dict]:
    """每个 key（按 hint）的活动统计：最近一次活动、近 7 天的动作数（不含读取）与读取数。
    审计只记录 hint；两把 key 的 hint 恰好相同时统计会合并（概率极小，只影响展示）。"""
    since = utcnow().replace(tzinfo=None) - timedelta(days=7)  # 库里存的是 UTC 无时区
    stats: dict[str, dict] = {}
    for actor, last in db.query(AuditLog.actor, func.max(AuditLog.created_at)).group_by(AuditLog.actor):
        stats[actor] = {"last_active_at": last, "actions_7d": 0, "reads_7d": 0}
    recent = db.query(AuditLog.actor, AuditLog.action, func.count()).filter(
        AuditLog.created_at >= since
    ).group_by(AuditLog.actor, AuditLog.action)
    for actor, action, n in recent:
        slot = stats.setdefault(actor, {"last_active_at": None, "actions_7d": 0, "reads_7d": 0})
        slot["reads_7d" if action == "pull" else "actions_7d"] += n
    return stats


@router.get("/keys", response_model=list[KeyListEntry])
def list_keys(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("key.read"))
):
    """密钥列表（不含明文 / 哈希），每把带上活动统计，供网页的 Agent 视图使用。"""
    stats = _key_activity(db)
    empty = {"last_active_at": None, "actions_7d": 0, "reads_7d": 0}
    return [{**_key_out(k), **stats.get(k.hint, empty)}
            for k in db.query(ApiKey).order_by(ApiKey.id).all() if _key_in_scope(key, k)]


@router.post("/keys", status_code=201, response_model=KeyCreatedOut, response_model_exclude_unset=True)
def create_key(
    body: KeyCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    """创建密钥（明文只返回这一次）。人用 CLI 创建（via=cli）；Agent 代人创建
    必须 via=natural_language 并附人同意创建的原话，来源与依据写进审计。"""
    role = perms.get_role(db, body.role)
    project_id = body.project_id
    if not _is_super(key):
        # 项目管理员：只能在自己的项目里建 key，且建不出带人类专属权限的角色（超级管理员的 project.manage 等）
        if key.project_id is None:
            raise ApiError("super_admin_required", "只有超级管理员能创建 key")
        if project_id is None:
            project_id = key.project_id
        if project_id != key.project_id:
            raise HTTPException(status_code=404, detail="project not found")
        if (perms.role_permissions(role) & perms.HUMAN_ONLY) - perms.role_permissions(key.role):
            raise ApiError("super_admin_required", f"角色 {role.name} 带有你没有的人类专属权限，只有超级管理员能创建这样的 key")
    if project_id is not None and db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    if perms.requires_project(role) and project_id is None:
        # 项目范围由 key 决定，不能靠 Agent 自己在调用里填：全局的 Agent key 能在任何项目里写；
        # 只有超级管理员（admin）可以是全局的
        raise ApiError(
            "project_required",
            f"角色 {role.name} 的 key 必须绑定项目（project_id）：先 list_projects 选一个项目；只有超级管理员 admin 的 key 可以是全局的",
        )
    if body.via == "natural_language" and not body.evidence.strip():
        raise HTTPException(
            status_code=422,
            detail="Agent 代人创建密钥必须附 evidence：人同意创建它的原话（先问人，不要自己决定）",
        )
    plaintext = new_key(role.kind)
    k = ApiKey(key=hash_key(plaintext), hint=key_hint(plaintext), prefix=role.kind,
               role_id=role.id, project_id=project_id, label=body.label, surface=body.surface.strip())
    db.add(k)
    db.flush()
    home = find_home()
    if perms.stores_key_file(role) and home is not None:
        # Agent 类 key 和网页用的只读 key：服务端直接写进 .speclock/keys/，响应里只给文件名，明文不经过对话
        k.key_file = keyfiles.save_key(home, role.name, body.label, k.id, plaintext)
    audit(db, key.hint, "key_create", f"apikey:{k.hint}",
          {"role": role.name, "label": k.label, "project_id": k.project_id,
           "via": body.via, "evidence": body.evidence, "key_file": k.key_file})
    db.commit()
    if k.key_file:
        out = {**_key_out(k),
               "notice": f"key 已保存到 {keyfiles.KEYS_DIRNAME}/{k.key_file}，明文不在这里返回；"
                         "把这个文件名交给要用它的 Agent，只有它自己去读"}
        if role.kind == "agent":
            # 可以直接写进那个 Agent 的 .mcp.json（用文件名而不是 key，SPECLOCK_HOME 写死）
            out["mcp_config"] = mcp_config(home, k.key_file)
        return out
    # 人类 key（或没有 .speclock/ 时）：明文仅此一次返回，此后任何地方都不可再见
    return {**_key_out(k), "key": plaintext,
            "notice": "此 key 仅此一次可见，请立即复制保存；系统只存哈希，无法找回"}


@router.delete("/keys/{key_id}", response_model=DeletedOut)
def delete_key(
    key_id: int,
    via: str = Query(default="api", pattern="^(cli|natural_language|api)$"),
    evidence: str = Query(default="", description="Agent 代人删除时：人同意的原话"),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    """删除（吊销）密钥，立即失效、不可恢复。Agent 代人删除须 via=natural_language 并附原话。"""
    if via == "natural_language" and not evidence.strip():
        raise HTTPException(
            status_code=422,
            detail="Agent 代人删除密钥必须附 evidence：人同意删除它的原话（先问人，不要自己决定）",
        )
    k = db.get(ApiKey, key_id)
    if k is None or not _key_in_scope(key, k):
        raise HTTPException(status_code=404, detail="key not found")
    if k.prefix == "human" and {"key.manage", "project.manage"} <= perms.role_permissions(k.role):
        if _count_admins(db, {k.id}) < 1:
            raise HTTPException(
                status_code=409,
                detail="这是最后一把超级管理员 key，删除后无人能管理系统，已拒绝",
            )
    audit(db, key.hint, "key_delete", f"apikey:{k.hint}",
          {"label": k.label, "via": via, "evidence": evidence})
    key_file = k.key_file
    db.delete(k)
    db.commit()
    keyfiles.delete_key_file(find_home(), key_file)
    return {"id": key_id, "deleted": True}


def _role_out(r: Role, key_count: int) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "kind": r.kind,
        "description": r.description,
        "permissions": json.loads(r.permissions_json or "[]"),
        "builtin": r.builtin,
        "key_count": key_count,
    }


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(key: ApiKey = Depends(require_permission("key.read"))):
    """权限目录（由代码定义；角色只能从中挑选）。"""
    return [
        {"name": name, "description": desc, "human_only": human_only}
        for name, (desc, human_only) in perms.PERMISSIONS.items()
    ]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("key.read"))
):
    counts: dict[int, int] = {}
    for k in db.query(ApiKey).all():
        if k.role_id is not None:
            counts[k.role_id] = counts.get(k.role_id, 0) + 1
    return [_role_out(r, counts.get(r.id, 0)) for r in db.query(Role).order_by(Role.id).all()]


@router.post("/roles", status_code=201, response_model=RoleOut)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    _require_super(key)
    if not ROLE_NAME_RE.match(body.name):
        raise HTTPException(status_code=422, detail="角色名须字母开头，仅含字母 / 数字 / _ / -，最长 40")
    if db.query(Role).filter(Role.name == body.name).first() is not None:
        raise HTTPException(status_code=409, detail=f"角色 {body.name} 已存在")
    try:
        granted = perms.validate_role(body.kind, body.permissions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    r = Role(name=body.name, kind=body.kind, description=body.description,
             permissions_json=json.dumps(granted), builtin=False)
    db.add(r)
    db.flush()
    audit(db, key.hint, "role_create", f"role:{r.name}", {"permissions": granted})
    db.commit()
    return _role_out(r, 0)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    """改角色的说明 / 权限映射（预置角色也可以改）。不允许改到「没有任何管理员」。"""
    _require_super(key)
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="role not found")
    if body.description is not None:
        r.description = body.description
    if body.permissions is not None:
        try:
            granted = perms.validate_role(r.kind, body.permissions)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if _count_admins(db, role_override={r.id: set(granted)}) < 1:
            raise HTTPException(
                status_code=409,
                detail="这样改会让系统里没有任何超级管理员（key.manage + project.manage 的 human key），已拒绝",
            )
        r.permissions_json = json.dumps(granted)
    audit(db, key.hint, "role_update", f"role:{r.name}",
          {"permissions": json.loads(r.permissions_json)})
    db.commit()
    count = db.query(ApiKey).filter(ApiKey.role_id == r.id).count()
    return _role_out(r, count)


@router.delete("/roles/{role_id}", response_model=DeletedOut)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    _require_super(key)
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="role not found")
    if r.builtin:
        raise HTTPException(status_code=409, detail="预置角色不能删除（可以改它的权限）")
    if db.query(ApiKey).filter(ApiKey.role_id == r.id).count():
        raise HTTPException(status_code=409, detail="仍有 key 绑定该角色，请先删除或更换这些 key")
    audit(db, key.hint, "role_delete", f"role:{r.name}", {})
    db.delete(r)
    db.commit()
    return {"id": role_id, "deleted": True}
