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
    """SQLite 增量迁移（幂等）：老库缺列时 ALTER TABLE ADD COLUMN。

    create_all 对已有表不会补列，这里用 PRAGMA table_info 检测后逐列补齐；
    列定义必须与 models.py 的默认值保持一致。
    """
    from sqlalchemy import text

    wanted = {
        "blocks": {
            "draft_rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "draft_edge_md": "TEXT NOT NULL DEFAULT ''",
        },
        "block_versions": {
            "rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "edge_md": "TEXT NOT NULL DEFAULT ''",
        },
    }
    engine = get_engine()
    with engine.begin() as conn:
        for table, cols in wanted.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def _backfill_draft_api_desc() -> None:
    """存量数据迁移（幂等）：草稿里缺 desc 的 API 回填 desc = name，
    保证旧模块下次发布不会被 desc 校验卡死。rules_json 刻意不回填
    （保持 []），作者下次发布时会被 422 引导补规则——这是设计意图。"""
    import json

    from speclock.models import Block

    db = SessionLocal()
    try:
        dirty = False
        for block in db.query(Block).all():
            apis = json.loads(block.draft_apis_json or "[]")
            touched = False
            for entry in apis:
                if isinstance(entry, dict) and not str(entry.get("desc", "") or "").strip():
                    entry["desc"] = str(entry.get("name", "") or "")
                    touched = True
            if touched:
                block.draft_apis_json = json.dumps(apis, ensure_ascii=False)
                dirty = True
        if dirty:
            db.commit()
    finally:
        db.close()


def init_db() -> None:
    from speclock import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())
    _ensure_columns()
    _backfill_draft_api_desc()


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
