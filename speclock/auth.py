"""API-key auth. Two key classes, two dependencies — the physical boundary
of the whole system:

- ``require_human`` guards every write endpoint (admin router).
- ``require_agent`` guards the read + proposal endpoints (agent router).

An ``agent-*`` key against any admin endpoint is always 403; a missing or
unknown key is 401. There is no endpoint that accepts both.
"""

from __future__ import annotations

import json
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from speclock.db import get_db
from speclock.models import ApiKey, AuditLog


def new_key(prefix: str) -> str:
    assert prefix in ("human", "agent")
    return f"{prefix}-{secrets.token_hex(16)}"


def _lookup(x_api_key: str | None, db: Session) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    rec = db.query(ApiKey).filter(ApiKey.key == x_api_key).first()
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


def audit(db: Session, actor: str, action: str, target: str, detail: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target=target,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
