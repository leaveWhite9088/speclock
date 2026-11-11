"""权限目录与预置角色。按权限放行的 FastAPI 依赖在 speclock_server.deps。

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

from fastapi import HTTPException
from sqlalchemy.orm import Session

from speclock_core.models import ApiKey, Role

# name -> (说明, 是否人类专属)
PERMISSIONS: dict[str, tuple[str, bool]] = {
    "spec.read": ("读取已发布规格：索引、小业务、模块、diff、版本历史", False),
    "exec.read": ("查看待办与执行记录（含锁定版本的完整上下文）", False),
    "exec.write": ("领取任务、报告阻塞 / 失败、提交实现结果", False),
    "exec.verify": ("独立验收他人提交的实现结果（不能验收自己实现的）", False),
    "cr.read": ("查看审核单与其 Commit", False),
    "cr.write": ("创建、编辑、提交、撤回审核单", False),
    "cr.approve": ("批准或驳回审核单（人的授权）", True),
    "cr.internal": ("开「内部整理」类审核单：不改变业务内容的重组，提交即生效、不经人批准（由提交者自行判断，Core 不检查内容）", False),
    "commit.write": ("在已批准的审核单下提交 Commit，改写规格库", False),
    "audit.read": ("查看审计日志与回执看板", False),
    "spec.delete": ("删除模块 / 小业务 / 大业务（须先归档其下的已发布模块；不可恢复，须附人同意的原话）", True),
    "project.manage": ("创建、重命名、删除项目", True),
    "key.read": ("查看密钥、角色与权限目录（只读，不含明文；网页的 Agent 页用）", False),
    "key.manage": ("管理密钥与角色", True),
}

HUMAN_ONLY = frozenset(name for name, (_, human_only) in PERMISSIONS.items() if human_only)

# name, kind, description, permissions
PRESET_ROLES: list[tuple[str, str, str, list[str]]] = [
    ("admin", "human", "超级管理员：拥有全部权限，key 可以是全局的（跨项目）", list(PERMISSIONS)),
    (
        "project-admin",
        "human",
        "项目管理员（项目主管）：管理本项目的 key、批准 / 驳回本项目的审核单；key 必须绑定项目，"
        "不能建项目、不能改角色、不能建超级管理员",
        ["spec.read", "exec.read", "cr.read", "cr.approve", "spec.delete", "key.read", "key.manage"],
    ),
    ("reviewer", "human", "审核人：只能查看并批准 / 驳回审核单", ["spec.read", "cr.read", "cr.approve"]),
    (
        "viewer",
        "human",
        "只读查看：网页自动使用的角色，能看规格、审核单、待办、活动、密钥列表，什么都改不了",
        ["spec.read", "cr.read", "exec.read", "audit.read", "key.read"],
    ),
    (
        "requirements-agent",
        "agent",
        "需求 Agent：整理审核单，并在审核单获批后写规格库",
        ["spec.read", "cr.read", "cr.write", "cr.internal", "commit.write", "exec.read"],
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
    (
        "scanner-agent",
        "agent",
        "扫描 Agent：通读规格找问题，只能提建议（和需求 Agent 讨论或请人确认），不能开审核单、不能改规格",
        ["spec.read", "cr.read", "exec.read"],
    ),
]

# 旧版预置角色升级时补上的权限（只在该角色完全没有 exec.* 权限时补一次）
EXEC_PERMISSIONS = ("exec.read", "exec.write", "exec.verify")

# 除 agent 类角色外，这些角色的 key 也必须绑定项目（只有超级管理员 admin 可以是全局的）
PROJECT_SCOPED_ROLES = frozenset({"project-admin"})


def requires_project(role: Role) -> bool:
    """这个角色的 key 是否必须绑定项目：Agent 类角色（项目范围由 key 决定，不能靠它自己在调用里填）和项目管理员。"""
    return role.kind == "agent" or role.name in PROJECT_SCOPED_ROLES


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


def _once(db: Session, name: str) -> bool:
    """一次性迁移标记：第一次调用返回 True 并写入标记，之后返回 False。"""
    from speclock_core.models import MigrationMark

    if db.get(MigrationMark, name) is not None:
        return False
    db.add(MigrationMark(name=name))
    return True


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
    # 清掉权限目录里已经不存在的权限名（如已删除的 ack.write / spec.void）
    for role in existing.values():
        have = json.loads(role.permissions_json or "[]")
        kept = [p for p in have if p in PERMISSIONS]
        if kept != have:
            role.permissions_json = json.dumps(sorted(kept))
    # 升级旧库：每项一次性迁移，用迁移标记表保证只做一次（管理员之后可以放心收回权限）
    if _once(db, "exec_permissions"):
        for name, _kind, _desc, perms in PRESET_ROLES:
            role = existing[name]
            have = set(json.loads(role.permissions_json or "[]"))
            if role.builtin and not (have & set(EXEC_PERMISSIONS)):
                add = {p for p in perms if p in EXEC_PERMISSIONS}
                if add:
                    role.permissions_json = json.dumps(sorted(have | add))
    if _once(db, "cr_internal_permission"):
        for name in ("admin", "requirements-agent"):
            role = existing.get(name)
            if role is not None and role.builtin:
                have = set(json.loads(role.permissions_json or "[]"))
                role.permissions_json = json.dumps(sorted(have | {"cr.internal"}))
    if _once(db, "scanner_cr_read"):
        # 扫描 Agent 要能读审核单，才知道规格「为什么这样定」、哪些问题已经在处理
        role = existing.get("scanner-agent")
        if role is not None and role.builtin:
            have = set(json.loads(role.permissions_json or "[]"))
            role.permissions_json = json.dumps(sorted(have | {"cr.read"}))
    if _once(db, "key_read_permission"):
        role = existing.get("admin")
        if role is not None and role.builtin:
            have = set(json.loads(role.permissions_json or "[]"))
            role.permissions_json = json.dumps(sorted(have | {"key.read"}))
    if _once(db, "spec_delete_permission"):
        for name in ("admin", "project-admin"):
            role = existing.get(name)
            if role is not None and role.builtin:
                have = set(json.loads(role.permissions_json or "[]"))
                role.permissions_json = json.dumps(sorted(have | {"spec.delete"}))
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
