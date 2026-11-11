"""Database engine / session management.

The SQLite URL is read from SPECLOCK_DB_URL, falling back to the database in
the discovered .speclock/ directory (see speclock_config). `configure()` re-points the
module-level engine; tests use it to get an isolated temporary database
per run.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from speclock_config import load_config


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        configure(os.environ.get("SPECLOCK_DB_URL") or load_config().db_url)
    return _engine


def configure(url: str) -> None:
    global _engine
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    SessionLocal.configure(bind=_engine)


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
