"""引导：建库并写入种子数据、初始化 ``.speclock/``、准备网页只读 key。

这是核心里最上层的一块——它把 db / models / permissions / executions 串起来，
下层模块都不依赖它。
"""

from __future__ import annotations

from pathlib import Path

from speclock_config import (
    GLOBAL_PORT,
    HOME_DIRNAME,
    WEB_KEY_LABEL,
    delete_legacy_web_key,
    Config,
    ensure_keys_dir,
    ensure_web_key_ignored,
    find_home,
    free_port,
    global_home,
    is_home,
    read_config,
    read_web_key,
    write_home,
    write_web_key,
)
from speclock_core import db as dbmod
from speclock_core.auth import backfill_audit_projects, hash_key, key_hint, new_key
from speclock_core.executions import backfill
from speclock_core.migrations import create_schema
from speclock_core.models import ApiKey, Project
from speclock_core.permissions import _once, get_role, seed_roles


def init_db() -> None:
    """建表 / 迁移，并补齐种子数据：预置角色、已发布模块缺的执行记录（都幂等）。"""
    create_schema()
    db = dbmod.SessionLocal()
    try:
        seed_roles(db)
        backfill(db)
        if _once(db, "audit_project_id"):
            backfill_audit_projects(db)
            db.commit()
    finally:
        db.close()


def ensure_web_key(project_id: int, home: Path | None = None) -> str | None:
    """确保这个项目有一把有效的网页只读 key（``viewer`` 角色、**绑定该项目**），返回明文；
    没有 .speclock/（如测试）返回 None。网页只用这把 key，所以只看得到这一个项目。
    调用前数据库必须已经 init_db（要用到 viewer 角色）。key 被删或文件丢了，下次需要时自动补一把。"""
    home = home or find_home()
    if home is None:
        return None
    key = read_web_key(home, project_id)
    db = dbmod.SessionLocal()
    try:
        row = db.query(ApiKey).filter(ApiKey.key == hash_key(key)).first() if key else None
        if row is not None and row.project_id == project_id:
            ensure_web_key_ignored(home)
            return key
        role = get_role(db, "viewer")
        key = new_key("human")
        db.add(ApiKey(key=hash_key(key), hint=key_hint(key), prefix=role.kind,
                      role_id=role.id, project_id=project_id, label=WEB_KEY_LABEL))
        db.commit()
    finally:
        db.close()
    write_web_key(home, key, project_id)
    return key


def retire_global_web_key(home: Path | None = None) -> None:
    """旧版给网页发过一把**全局**的只读 key（能看到所有项目）：删掉库里的记录和 web.key 文件。
    幂等；每次启动都做一遍，所以哪怕是被人拷回来的旧文件也会被清掉。"""
    home = home or find_home()
    db = dbmod.SessionLocal()
    try:
        db.query(ApiKey).filter(ApiKey.label == WEB_KEY_LABEL, ApiKey.project_id.is_(None)).delete()
        db.commit()
    finally:
        db.close()
    if home is not None:
        delete_legacy_web_key(home)


def init_home(root: Path, *, glob: bool = False, project_name: str | None = None,
              port: int | None = None, new_admin: bool = False) -> tuple[Config, str | None]:
    """创建（或补全）.speclock/，建库、建项目、生成一把**随机** admin key。

    返回 (配置, admin key 明文或 None)。库里已经有 key 就不再生成（明文无法找回，
    只显示 hint），返回 None。``new_admin=True`` 在已有 key 的库里**再发一把** admin key
    （admin key 丢了的恢复办法：能在本机跑这条命令，就等于拥有这个库）。
    """
    home = global_home() if glob else root / HOME_DIRNAME
    if not is_home(home):
        write_home(home, port or (GLOBAL_PORT if glob else free_port()))
    cfg = read_config(home)

    dbmod.configure(cfg.db_url)
    init_db()

    session = dbmod.SessionLocal()
    try:
        if not new_admin and session.query(ApiKey).filter(ApiKey.label != WEB_KEY_LABEL).count():
            retire_global_web_key(home)
            ensure_keys_dir(home)
            return cfg, None
        project = session.query(Project).first()
        if project is None:
            project = Project(name=project_name or (root.resolve().name or "我的项目"))
            session.add(project)
            session.flush()
        key = new_key("human")
        role = get_role(session, "admin")
        session.add(ApiKey(key=hash_key(key), hint=key_hint(key), prefix=role.kind,
                           role_id=role.id, project_id=None, label="admin"))
        session.commit()
        project_id = project.id
    finally:
        session.close()
    ensure_web_key(project_id, home)  # 这个项目的网页只读 key（绑定项目，网页只看得到它）
    ensure_keys_dir(home)  # Agent key 的存放目录 + README
    return cfg, key
