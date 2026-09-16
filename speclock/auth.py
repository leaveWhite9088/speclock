"""API-key auth. Two key classes — the physical boundary of the whole system:

- ``require_human`` guards every write endpoint (admin router).
- ``require_agent`` guards the read + proposal endpoints (agent router).
- ``require_reader`` accepts either class; used only by the shared diff read
  endpoint, which applies agent-only visibility checks itself by key prefix.

An ``agent-*`` key against any admin endpoint is always 403; a missing or
unknown key is 401.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from speclock.db import get_db
from speclock.models import ApiKey, AuditLog


def new_key(prefix: str) -> str:
    assert prefix in ("human", "agent")
    return f"{prefix}-{secrets.token_hex(16)}"


def hash_key(key: str) -> str:
    """密钥明文 → SHA-256 hex。数据库只存这个值，明文永不落库。"""
    return hashlib.sha256(key.encode()).hexdigest()


def key_hint(key: str) -> str:
    """展示用脱敏形式，如 human-…1a2b（用于列表/审计/回执，可安全落库）。"""
    return f"{key.split('-', 1)[0]}-…{key[-4:]}"


def _lookup(x_api_key: str | None, db: Session) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    rec = db.query(ApiKey).filter(ApiKey.key == hash_key(x_api_key)).first()
    if rec is None:
        raise HTTPException(status_code=401, detail="unknown API key")
    return rec


def require_human(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    rec = _lookup(x_api_key, db)
    if rec.prefix != "human":
        raise HTTPException(
            status_code=403,
            detail="write endpoints require a human-* key; agent keys are read-only by design",
        )
    return rec


def require_agent(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    rec = _lookup(x_api_key, db)
    if rec.prefix != "agent":
        raise HTTPException(
            status_code=403,
            detail="read endpoints require an agent-* key; humans use the admin API or UI",
        )
    return rec


def require_reader(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """读端点（human / agent key 均可）。仅用于人机共用的 diff 读端点：
    agent 的可见性约束（published 状态 / 项目隔离）由端点按 prefix 自行施加。"""
    return _lookup(x_api_key, db)


def audit(db: Session, actor: str, action: str, target: str, detail: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
