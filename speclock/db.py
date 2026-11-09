"""Database engine / session management.

The SQLite URL is read from SPECLOCK_DB_URL, falling back to the active
profile in speclock.toml (see settings.py). `configure()` re-points the
module-level engine; tests use it to get an isolated temporary database
per run.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from speclock.settings import load_settings


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        configure(os.environ.get("SPECLOCK_DB_URL") or load_settings().db_url)
    return _engine


def configure(url: str) -> None:
    global _engine
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    SessionLocal.configure(bind=_engine)


def _ensure_columns() -> None:
    """SQLite 增量迁移（幂等）：老库缺列时 ALTER TABLE ADD COLUMN；已废弃的列
    DROP COLUMN（SQLite ≥ 3.35）。

    create_all 对已有表不会补列/删列，这里用 PRAGMA table_info 检测后处理；
    列定义必须与 models.py 的默认值保持一致。
    """
    from sqlalchemy import text

    wanted = {
        "blocks": {
            "draft_rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "draft_acceptance_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "capabilities": {
            "summary": "TEXT NOT NULL DEFAULT ''",
        },
        "block_versions": {
            "rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_json": "TEXT NOT NULL DEFAULT '[]'",
            "level": "TEXT NOT NULL DEFAULT ''",
            "cr_id": "INTEGER REFERENCES change_requests(id)",
            "commit_id": "INTEGER REFERENCES commits(id)",
        },
        "capability_versions": {
            "cr_id": "INTEGER REFERENCES change_requests(id)",
            "commit_id": "INTEGER REFERENCES commits(id)",
        },
        "api_keys": {
            "role_id": "INTEGER REFERENCES roles(id)",
        },
        "change_requests": {
            "kind": "TEXT NOT NULL DEFAULT 'business'",
            "kind_reason": "TEXT NOT NULL DEFAULT ''",
        },
    }
    dropped = {
        "capabilities": ["doc_type"],
        "blocks": ["draft_edge_md", "draft_nfr_md", "completed", "completed_version", "completed_at"],
        "block_versions": ["edge_md", "nfr_md", "applied_ops_json", "voided_at"],
    }
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS acks"))  # 旧的实现回执，已被执行记录取代
        for table, cols in wanted.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            for col in dropped.get(table, []):
                if col in existing:
                    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))


def _rename_legacy_tables() -> None:
    """存量迁移（幂等）：Domain/Document 改名为 Business/Capability。

    表 domains→businesses、documents→capabilities、document_versions→
    capability_versions，外键列 domain_id→business_id、document_id→
    capability_id。必须在 create_all 之前执行，否则会建出空的新表。
    RENAME 不动数据，SQLite 会同步改写其他表里指向它们的外键。
    """
    from sqlalchemy import text

    def tables(conn) -> set[str]:
        return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}

    def columns(conn, table: str) -> set[str]:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}

    table_renames = [
        ("domains", "businesses"),
        ("documents", "capabilities"),
        ("document_versions", "capability_versions"),
    ]
    column_renames = [
        ("capabilities", "domain_id", "business_id"),
        ("capability_versions", "document_id", "capability_id"),
        ("blocks", "document_id", "capability_id"),
    ]
    with get_engine().begin() as conn:
        for old, new in table_renames:
            have = tables(conn)
            if old in have and new not in have:
                conn.execute(text(f"ALTER TABLE {old} RENAME TO {new}"))
        for table, old, new in column_renames:
            if table in tables(conn) and old in columns(conn, table):
                conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))


def init_db() -> None:
    from speclock import models  # noqa: F401  (register tables)

    _rename_legacy_tables()
    Base.metadata.create_all(get_engine())
    _ensure_columns()
    from speclock.executions import backfill
    from speclock.permissions import seed_roles

    db = SessionLocal()
    try:
        seed_roles(db)
        backfill(db)  # 给已发布的模块补执行记录（幂等）
    finally:
        db.close()


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
