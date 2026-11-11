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

from speclock_core.models import AuditLog


def new_key(prefix: str) -> str:
    assert prefix in ("human", "agent")
    return f"{prefix}-{secrets.token_hex(16)}"


def hash_key(key: str) -> str:
    """密钥明文 → SHA-256 hex。数据库只存这个值，明文永不落库。"""
    return hashlib.sha256(key.encode()).hexdigest()


def key_hint(key: str) -> str:
    """展示用脱敏形式，如 human-…1a2b（用于列表/审计/回执，可安全落库）。"""
    return f"{key.split('-', 1)[0]}-…{key[-4:]}"


def audit(db: Session, actor: str, action: str, target: str, detail: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
