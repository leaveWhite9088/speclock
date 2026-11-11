"""按权限放行的 FastAPI 依赖：key 绑定角色，角色是权限集合，接口声明自己需要哪些权限。

缺失或未知的 key 是 401，权限不足是 403。
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from speclock_core import PERMISSIONS, ApiKey, get_db, hash_key, role_permissions


def lookup_key(x_api_key: str | None, db: Session) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    rec = db.query(ApiKey).filter(ApiKey.key == hash_key(x_api_key)).first()
    if rec is None:
        if db.query(ApiKey).count() == 0:
            raise HTTPException(
                status_code=401,
                detail="unknown API key：数据库里还没有任何密钥（可能刚清库或换了库）。"
                "运行 speclock init 补一把 admin key；"
                "清库前创建的其他 key 随库一起失效，需要重新创建",
            )
        raise HTTPException(status_code=401, detail="unknown API key")
    return rec


def require_permission(*needed: str):
    """FastAPI 依赖工厂：key 的角色必须拥有 ``needed`` 里的**全部**权限，否则 403。
    缺失或未知的 key 是 401。返回 ApiKey 记录。"""
    assert needed and all(n in PERMISSIONS for n in needed), needed

    def dependency(
        x_api_key: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ) -> ApiKey:
        rec = lookup_key(x_api_key, db)
        have = role_permissions(rec.role)
        missing = [n for n in needed if n not in have]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"当前密钥的角色缺少权限：{'、'.join(missing)}",
            )
        return rec

    return dependency


def require_key(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """只要求是有效 key（不看权限），如 ``/me``。"""
    return lookup_key(x_api_key, db)
