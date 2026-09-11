"""Database engine / session management.

The SQLite URL is read from SPECLOCK_DB_URL (default: ./speclock.db).
`configure()` re-points the module-level engine; tests use it to get an
isolated temporary database per run.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DB_URL = "sqlite:///speclock.db"


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        configure(os.environ.get("SPECLOCK_DB_URL", DEFAULT_DB_URL))
    return _engine


def configure(url: str) -> None:
    global _engine
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    SessionLocal.configure(bind=_engine)


def init_db() -> None:
    from speclock import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())


def get_db():
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
