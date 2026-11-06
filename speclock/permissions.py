"""权限目录、预置角色与按权限放行的鉴权依赖。

模型：key 绑定**角色**，角色是**权限集合**。
- 权限目录（``PERMISSIONS``）由代码定义——一条权限只有在某个接口真的检查它时才有意义，
  所以不开放自定义新权限名；
- 角色与「角色 → 权限」的映射完全可配置（预置角色可改权限、不可删）；
- 角色有 ``kind``（human / agent），决定 key 的物理类别与明文前缀；**人类专属权限**
  （``human_only``，如批准审核单）不允许挂在 agent 类角色上——「Agent 不能替人批准」
  因此是物理约束，而不是提示词约束。
"""

from __future__ import annotations

import json

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from speclock.auth import hash_key
from speclock.db import get_db
from speclock.models import ApiKey, Role

# name -> (说明, 是否人类专属)
PERMISSIONS: dict[str, tuple[str, bool]] = {
    "spec.read": ("读取已发布规格：索引、小业务、模块、diff、版本历史", False),
    "exec.read": ("查看待办与执行记录（含锁定版本的完整上下文）", False),
    "exec.write": ("领取任务、报告阻塞 / 失败、提交实现结果", False),
    "exec.verify": ("独立验收他人提交的实现结果（不能验收自己实现的）", False),
    "cr.read": ("查看审核单与其 Commit", False),
    "cr.write": ("创建、编辑、提交、撤回审核单", False),
    "cr.approve": ("批准或驳回审核单（人的授权）", True),
    "commit.write": ("在已批准的审核单下提交 Commit，改写规格库", False),
    "audit.read": ("查看审计日志与回执看板", False),
    "project.manage": ("创建、重命名、删除项目", True),
    "key.manage": ("管理密钥与角色", True),
}

HUMAN_ONLY = frozenset(name for name, (_, human_only) in PERMISSIONS.items() if human_only)

# name, kind, description, permissions
PRESET_ROLES: list[tuple[str, str, str, list[str]]] = [
    ("admin", "human", "管理员：拥有全部权限", list(PERMISSIONS)),
    ("reviewer", "human", "审核人：只能查看并批准 / 驳回审核单", ["spec.read", "cr.read", "cr.approve"]),
    (
        "requirements-agent",
        "agent",
        "需求 Agent：整理审核单，并在审核单获批后写规格库",
        ["spec.read", "cr.read", "cr.write", "commit.write", "exec.read"],
    ),
    (
        "executor-agent",
        "agent",
        "执行 Agent：领取任务、按锁定版本实现、提交实现结果",
        ["spec.read", "cr.read", "exec.read", "exec.write"],
    ),
    (
        "tester-agent",
        "agent",
        "测试 Agent：独立验收执行 Agent 提交的实现结果",
        ["spec.read", "cr.read", "exec.read", "exec.verify"],
    ),
    ("scanner-agent", "agent", "扫描 Agent：只读规格", ["spec.read"]),
]

# 旧版预置角色升级时补上的权限（只在该角色完全没有 exec.* 权限时补一次）
EXEC_PERMISSIONS = ("exec.read", "exec.write", "exec.verify")

LEGACY_DEFAULT_ROLE = {"human": "admin", "agent": "executor-agent"}


def validate_role(kind: str, permissions: list[str]) -> list[str]:
    """校验并规范化权限列表（去重、排序）；非法时抛 ValueError（调用方转 422）。"""
    if kind not in ("human", "agent"):
        raise ValueError("kind 必须是 human 或 agent")
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        raise ValueError(f"未知权限：{'、'.join(unknown)}")
    if kind == "agent":
        forbidden = sorted(set(permissions) & HUMAN_ONLY)
        if forbidden:
            raise ValueError(f"agent 类角色不能拥有人类专属权限：{'、'.join(forbidden)}")
    return sorted(set(permissions))


def seed_roles(db: Session) -> None:
    """幂等：补齐预置角色（已存在的不覆盖，管理员可能已改过权限）；并给没有角色的
    老 key 回填默认角色（human→admin，agent→executor-agent）。"""
    existing = {r.name: r for r in db.query(Role).all()}
    for name, kind, description, perms in PRESET_ROLES:
        if name not in existing:
            existing[name] = Role(
                name=name,
                kind=kind,
                description=description,
                permissions_json=json.dumps(sorted(perms)),
                builtin=True,
            )
            db.add(existing[name])
    db.flush()
    # 升级旧库：预置角色若还没有任何 exec.* 权限，补上预置里对应的那几条
    for name, _kind, _desc, perms in PRESET_ROLES:
        role = existing[name]
        have = set(json.loads(role.permissions_json or "[]"))
        if role.builtin and not (have & set(EXEC_PERMISSIONS)):
            add = {p for p in perms if p in EXEC_PERMISSIONS}
            if add:
                role.permissions_json = json.dumps(sorted(have | add))
    for key in db.query(ApiKey).filter(ApiKey.role_id.is_(None)).all():
        key.role_id = existing[LEGACY_DEFAULT_ROLE[key.prefix]].id
    db.commit()


def role_permissions(role: Role | None) -> set[str]:
    if role is None:
        return set()
    return set(json.loads(role.permissions_json or "[]")) & set(PERMISSIONS)


def get_role(db: Session, name: str) -> Role:
    role = db.query(Role).filter(Role.name == name).first()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role {name!r} not found")
    return role


def lookup_key(x_api_key: str | None, db: Session) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    rec = db.query(ApiKey).filter(ApiKey.key == hash_key(x_api_key)).first()
    if rec is None:
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
