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
    WEB_ROLE,
    Config,
    delete_legacy_web_files,
    ensure_keys_dir,
    find_home,
    free_port,
    global_home,
    is_home,
    read_config,
    read_key,
    save_key,
    write_home,
)
from speclock_core import db as dbmod
from speclock_core.auth import backfill_audit_projects, hash_key, key_hint, new_key
from speclock_core.executions import backfill
from speclock_core.migrations import create_schema
from speclock_core.models import ApiKey, Project, Role
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


def find_web_key(project_id: int, home: Path | None = None) -> str | None:
    """这个项目的网页只读 key 明文：绑定该项目的 ``viewer`` key，存在 ``.speclock/keys/`` 的 key 文件里
    （和其他 key 一样）。没有这样的 key、或文件读不到 / 和库里的哈希对不上，返回 None。"""
    home = home or find_home()
    if home is None:
        return None
    db = dbmod.SessionLocal()
    try:
        rows = (db.query(ApiKey).join(Role, ApiKey.role_id == Role.id)
                .filter(Role.name == WEB_ROLE, ApiKey.project_id == project_id, ApiKey.key_file != "")
                .order_by(ApiKey.id).all())
        for row in rows:
            try:
                key = read_key(row.key_file, home, strict=True)
            except (OSError, ValueError):
                continue
            if hash_key(key) == row.key:
                return key
    finally:
        db.close()
    return None


def ensure_web_key(project_id: int, home: Path | None = None) -> str | None:
    """确保这个项目有一把网页只读 key（``viewer`` 角色、**绑定该项目**、存成 key 文件，和其他 key 一样），
    返回明文；没有 .speclock/（如测试）返回 None。网页只用这把 key，所以只看得到这一个项目。
    调用前数据库必须已经 init_db（要用到 viewer 角色）。已经有就不再建。"""
    home = home or find_home()
    if home is None:
        return None
    existing = find_web_key(project_id, home)
    if existing:
        return existing
    db = dbmod.SessionLocal()
    try:
        role = get_role(db, WEB_ROLE)
        key = new_key(role.kind)
        row = ApiKey(key=hash_key(key), hint=key_hint(key), prefix=role.kind, role_id=role.id,
                     project_id=project_id, label=WEB_KEY_LABEL)
        db.add(row)
        db.flush()
        row.key_file = save_key(home, role.name, f"{WEB_KEY_LABEL}-p{project_id}", row.id, key)
        db.commit()
    finally:
        db.close()
    return key


def ensure_web_keys(home: Path | None = None) -> None:
    """给每个还没有网页只读 key 的项目补一把（启动时做；新项目创建时也会建）。"""
    db = dbmod.SessionLocal()
    try:
        ids = [p.id for p in db.query(Project).order_by(Project.id).all()]
    finally:
        db.close()
    for pid in ids:
        ensure_web_key(pid, home)


def retire_legacy_web_keys(home: Path | None = None) -> None:
    """旧版给网页发过的 key 不再用：库里标签是 web、却没有 key 文件的那些（旧版那把**全局**的、能看全库的，
    和上一版每项目一把存在 web-keys/ 里的），以及 web.key / web-keys/ 文件，都清掉。幂等，每次启动做一遍。"""
    home = home or find_home()
    db = dbmod.SessionLocal()
    try:
        db.query(ApiKey).filter(ApiKey.label == WEB_KEY_LABEL, ApiKey.key_file == "").delete()
        db.commit()
    finally:
        db.close()
    if home is not None:
        delete_legacy_web_files(home)


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
            retire_legacy_web_keys(home)
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
