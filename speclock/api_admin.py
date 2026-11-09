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

from speclock import keyfiles
from speclock import permissions as perms
from speclock.api_agent import _check_project_scope
from speclock.auth import audit, hash_key, key_hint, new_key
from speclock.db import get_db
from speclock.engine import published_version
from speclock.home import find_home
from speclock.models import (
    ApiKey,
    AuditLog,
    Block,
    BlockVersion,
    Capability,
    CapabilityVersion,
    ChangeRequest,
    Commit,
    ExecutionEvent,
    ExecutionRecord,
    Project,
    Role,
    utcnow,
)
from speclock.permissions import require_key, require_permission
from speclock.schemas import (
    KeyCreate,
    ProjectCreate,
    RenameRequest,
    RoleCreate,
    RoleUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["admin"])

ROLE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")


def _get_block(db: Session, block_id: int) -> Block:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    return block


# ---------- 当前 key 是谁 ----------


@router.get("/me")
def whoami(key: ApiKey = Depends(require_key)):
    """当前 key 的身份与权限（MCP 客户端据此只暴露有权限的工具）。"""
    return {
        "key_id": key.id,
        "hint": key.hint,
        "kind": key.prefix,
        "label": key.label,
        "project_id": key.project_id,
        "role": key.role.name if key.role else None,
        "permissions": sorted(perms.role_permissions(key.role)),
    }


# ---------- SPA read endpoints（读操作不写审计） ----------


@router.get("/tree")
def get_tree(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))
):
    """全量聚合树：projects → businesses → capabilities → blocks，供 SPA 文档树主页
    一次拉取。含全部状态（draft / published / archived）的模块。"""
    published_at_map = {
        (bv.block_id, bv.version): bv.published_at
        for bv in db.query(BlockVersion).all()
    }
    exec_status = {
        (r.block_id, r.version): r.status for r in db.query(ExecutionRecord).all()
    }
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
                                    "execution_status": exec_status.get(
                                        (b.id, b.current_published_version)
                                    ),
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


@router.get("/archive")
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


@router.get("/activity")
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
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("audit.read")),
):
    """审计日志（新的在前，按 id 倒序）。所有筛选条件可以组合；翻页用 ``before_id``
    （传上一页最后一条的 id）。actor_prefix 可按 key 前缀过滤（如 ``agent`` 只看 AI 活动）。"""
    q = db.query(AuditLog)
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


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))
):
    return [
        {"id": p.id, "name": p.name}
        for p in db.query(Project).order_by(Project.id).all()
        if key.project_id is None or key.project_id == p.id
    ]


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("project.manage")),
):
    p = Project(name=body.name)
    db.add(p)
    audit(db, key.hint, "project_create", f"project:{body.name}", {})
    db.commit()
    return {"id": p.id, "name": p.name}


@router.put("/projects/{project_id}")
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


def _hard_delete_capability(db: Session, doc: Capability) -> None:
    published = [b for b in doc.blocks if b.status == "published"]
    if published:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "小业务下仍有已发布模块，请先（通过审核单）归档这些模块再删除",
                "published_blocks": [{"id": b.id, "title": b.title} for b in published],
            },
        )
    for b in doc.blocks:
        _hard_delete_block(db, b)
    db.query(CapabilityVersion).filter(CapabilityVersion.capability_id == doc.id).delete()
    db.delete(doc)


def _count_admins(
    db: Session,
    exclude_key_ids: set[int] = frozenset(),
    role_override: dict[int, set[str]] | None = None,
) -> int:
    """假设做了某些变更后，还有多少把 human key 拥有 key.manage（防止把自己锁在门外）。"""
    n = 0
    for k in db.query(ApiKey).filter(ApiKey.prefix == "human").all():
        if k.id in exclude_key_ids or k.role is None:
            continue
        have = (role_override or {}).get(k.role_id)
        if have is None:
            have = perms.role_permissions(k.role)
        if "key.manage" in have:
            n += 1
    return n


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("project.manage")),
):
    """项目删除：仅当其下无已发布模块时允许，否则 409 提示先归档模块。
    删除时级联硬删全部 大业务/小业务/模块/版本历史/审核单，并一并删除绑定到
    该项目的 API key（避免遗留 key 失效语义不清）。"""
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
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
          {"name": p.name, "deleted_keys": len(bound_keys), "deleted_crs": len(cr_ids)})
    db.delete(p)
    db.commit()
    return {"id": project_id, "deleted": True, "deleted_keys": len(bound_keys)}


# ---------- versions（读） ----------


def _trace(v) -> dict:
    return {"cr_id": v.cr_id, "commit_id": v.commit_id}


@router.get("/blocks/{block_id}/versions")
def list_versions(
    block_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """版本历史列表。每个版本附带该版本的执行记录（状态 + 事件历史）。"""
    block = _get_block(db, block_id)
    _check_project_scope(key, block.capability.business.project_id)
    records = {
        r.version: r
        for r in db.query(ExecutionRecord).filter(ExecutionRecord.block_id == block.id).all()
    }
    current = block.current_published_version
    out = []
    for v in block.versions:
        rec = records.get(v.version)
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
                "work_id": rec.id if rec else None,
                "execution_status": rec.status if rec else None,
                "events": [
                    {
                        "event": e.event,
                        "from": e.from_status,
                        "to": e.to_status,
                        "actor": e.actor,
                        "note": e.note,
                        "created_at": e.created_at,
                    }
                    for e in (rec.events if rec else [])
                ],
            }
        )
    return out


@router.get("/blocks/{block_id}/versions/{version}")
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
    rec = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.block_id == block.id, ExecutionRecord.version == bv.version)
        .first()
    )
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
        "work_id": rec.id if rec else None,
        "execution_status": rec.status if rec else None,
    }


@router.get("/capabilities/{capability_id}/versions")
def list_capability_versions(
    capability_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    doc = db.get(Capability, capability_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="capability not found")
    _check_project_scope(key, doc.business.project_id)
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


@router.get("/keys")
def list_keys(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("key.read"))
):
    """密钥列表（不含明文 / 哈希），每把带上活动统计，供网页的 Agent 视图使用。"""
    stats = _key_activity(db)
    empty = {"last_active_at": None, "actions_7d": 0, "reads_7d": 0}
    return [{**_key_out(k), **stats.get(k.hint, empty)} for k in db.query(ApiKey).order_by(ApiKey.id).all()]


@router.post("/keys", status_code=201)
def create_key(
    body: KeyCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    """创建密钥（明文只返回这一次）。人用 CLI 创建（via=cli）；Agent 代人创建
    必须 via=natural_language 并附人同意创建的原话，来源与依据写进审计。"""
    role = perms.get_role(db, body.role)
    if body.project_id is not None and db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    if body.via == "natural_language" and not body.evidence.strip():
        raise HTTPException(
            status_code=422,
            detail="Agent 代人创建密钥必须附 evidence：人同意创建它的原话（先问人，不要自己决定）",
        )
    plaintext = new_key(role.kind)
    k = ApiKey(key=hash_key(plaintext), hint=key_hint(plaintext), prefix=role.kind,
               role_id=role.id, project_id=body.project_id, label=body.label)
    db.add(k)
    db.flush()
    home = find_home()
    if role.kind == "agent" and home is not None:
        # Agent 类 key：服务端直接写进 .speclock/keys/，响应里只给文件名，明文不经过对话
        k.key_file = keyfiles.save_key(home, role.name, body.label, k.id, plaintext)
    audit(db, key.hint, "key_create", f"apikey:{k.hint}",
          {"role": role.name, "label": k.label, "project_id": k.project_id,
           "via": body.via, "evidence": body.evidence, "key_file": k.key_file})
    db.commit()
    if k.key_file:
        return {**_key_out(k),
                "notice": f"key 已保存到 {keyfiles.KEYS_DIRNAME}/{k.key_file}，明文不在这里返回；"
                          "把这个文件名交给要用它的 Agent，只有它自己去读"}
    # 人类 key（或没有 .speclock/ 时）：明文仅此一次返回，此后任何地方都不可再见
    return {**_key_out(k), "key": plaintext,
            "notice": "此 key 仅此一次可见，请立即复制保存；系统只存哈希，无法找回"}


@router.delete("/keys/{key_id}")
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
    if k is None:
        raise HTTPException(status_code=404, detail="key not found")
    if k.prefix == "human" and "key.manage" in perms.role_permissions(k.role):
        if _count_admins(db, {k.id}) < 1:
            raise HTTPException(
                status_code=409,
                detail="这是最后一把管理员 key（拥有 key.manage），删除后无人能管理系统，已拒绝",
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


@router.get("/permissions")
def list_permissions(key: ApiKey = Depends(require_permission("key.read"))):
    """权限目录（由代码定义；角色只能从中挑选）。"""
    return [
        {"name": name, "description": desc, "human_only": human_only}
        for name, (desc, human_only) in perms.PERMISSIONS.items()
    ]


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("key.read"))
):
    counts: dict[int, int] = {}
    for k in db.query(ApiKey).all():
        if k.role_id is not None:
            counts[k.role_id] = counts.get(k.role_id, 0) + 1
    return [_role_out(r, counts.get(r.id, 0)) for r in db.query(Role).order_by(Role.id).all()]


@router.post("/roles", status_code=201)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
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


@router.put("/roles/{role_id}")
def update_role(
    role_id: int,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
    """改角色的说明 / 权限映射（预置角色也可以改）。不允许改到「没有任何管理员」。"""
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
                detail="这样改会让系统里没有任何拥有 key.manage 的 human key，已拒绝",
            )
        r.permissions_json = json.dumps(granted)
    audit(db, key.hint, "role_update", f"role:{r.name}",
          {"permissions": json.loads(r.permissions_json)})
    db.commit()
    count = db.query(ApiKey).filter(ApiKey.role_id == r.id).count()
    return _role_out(r, count)


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("key.manage")),
):
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
