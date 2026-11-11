"""API-key 工具：生成、哈希、脱敏、审计。

鉴权本身（按权限放行）在 ``permissions.require_permission``：key 绑定角色，角色是
权限集合；key 的前缀（human-* / agent-*）是物理类别，由角色的 kind 决定。人类专属
权限（如批准审核单）不可挂在 agent 类角色上，所以 agent key 永远批准不了任何东西。
缺失或未知的 key 是 401，权限不足是 403。
"""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlalchemy.orm import Session

from speclock_core.models import (
    ApiKey, AuditLog, Block, Business, Capability, ChangeRequest, ExecutionRecord, Project,
)


def new_key(prefix: str) -> str:
    assert prefix in ("human", "agent")
    return f"{prefix}-{secrets.token_hex(16)}"


def hash_key(key: str) -> str:
    """密钥明文 → SHA-256 hex。数据库只存这个值，明文永不落库。"""
    return hashlib.sha256(key.encode()).hexdigest()


def key_hint(key: str) -> str:
    """展示用脱敏形式，如 human-…1a2b（用于列表/审计/回执，可安全落库）。"""
    return f"{key.split('-', 1)[0]}-…{key[-4:]}"


def infer_project_id(db: Session, actor: str, target: str, detail: dict | None = None) -> int | None:
    """一条审计记录属于哪个项目：先看对象（block / capability / cr / work / business / project），
    再看 detail 里写明的 project_id，最后看操作者这把 key 绑定的项目。推不出来就是 None
    （只有全局 key 看得到）。"""
    kind, _, rest = target.partition(":")
    ident = rest.split("@", 1)[0].split("/", 1)[0]
    try:
        n = int(ident)
    except ValueError:
        n = None
    if n is not None:
        if kind == "block" and (b := db.get(Block, n)) is not None:
            return b.capability.business.project_id
        if kind == "work":
            rec = db.query(ExecutionRecord).filter(ExecutionRecord.block_id == n).first()
            if rec is not None:
                return rec.block.capability.business.project_id
        if kind == "capability" and (c := db.get(Capability, n)) is not None:
            return c.business.project_id
        if kind == "business" and (bz := db.get(Business, n)) is not None:
            return bz.project_id
        if kind == "cr" and (cr := db.get(ChangeRequest, n)) is not None:
            return cr.project_id
        if kind == "project" and db.get(Project, n) is not None:
            return n
    if detail and isinstance(detail.get("project_id"), int):
        return detail["project_id"]
    bound = {k.project_id for k in db.query(ApiKey).filter(ApiKey.hint == actor).all()}
    return bound.pop() if len(bound) == 1 else None


def audit(db: Session, actor: str, action: str, target: str, detail: dict | None = None,
          project_id: int | None = None) -> None:
    """写一条审计记录。``project_id`` 不传就按对象 / detail / 操作者推（见 ``infer_project_id``）；
    对象马上要被删掉的（删模块、删项目）要在删之前显式传。"""
    db.flush()  # 同一事务里刚建的对象也要能查到
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
            project_id=project_id if project_id is not None else infer_project_id(db, actor, target, detail),
        )
    )


def backfill_audit_projects(db: Session) -> None:
    """给升级前没有 project_id 的老记录补上（尽力而为，推不出来的保持 NULL）。"""
    for row in db.query(AuditLog).filter(AuditLog.project_id.is_(None)).all():
        row.project_id = infer_project_id(db, row.actor, row.target, json.loads(row.detail_json or "{}"))
