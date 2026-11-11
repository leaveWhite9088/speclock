"""库结构迁移与建表（幂等）：老库缺列就补、改名过的表就改回来，然后 create_all。

只动表结构，不写任何数据；种子数据（预置角色、执行记录补齐）在 ``bootstrap.init_db``。
"""

from __future__ import annotations

from speclock_core import models  # noqa: F401  (register tables)
from speclock_core.db import Base, get_engine


def _ensure_columns() -> None:
    """SQLite 增量迁移（幂等）：老库缺列时 ALTER TABLE ADD COLUMN；已废弃的列
    DROP COLUMN（SQLite ≥ 3.35）。

    create_all 对已有表不会补列/删列，这里用 PRAGMA table_info 检测后处理；
    列定义必须与 models.py 的默认值保持一致。
    """
    from sqlalchemy import text

    wanted = {
        "blocks": {
            "draft_surfaces_json": "TEXT NOT NULL DEFAULT '[]'",
            "draft_rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "draft_acceptance_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "capabilities": {
            "summary": "TEXT NOT NULL DEFAULT ''",
        },
        "block_versions": {
            "rules_json": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_json": "TEXT NOT NULL DEFAULT '[]'",
            "surfaces_json": "TEXT NOT NULL DEFAULT '[]'",
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
            "key_file": "TEXT NOT NULL DEFAULT ''",
            "surface": "TEXT NOT NULL DEFAULT ''",
        },
        "audit_logs": {
            "project_id": "INTEGER",
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


def _rebuild_execution_records() -> None:
    """老库的执行记录表唯一约束是 (block_id, version)，按端分开以后要改成 (block_id, version, surface)。
    SQLite 改不了约束，只能重建表（建新表 → 拷数据 → 删旧表 → 改名）。已有的记录都是默认端（surface = ''），
    其余数据原样保留（含 id，事件表里的 record_id 照旧指得上）。幂等：已经有 surface 列就什么都不做。"""
    from sqlalchemy import text

    with get_engine().begin() as conn:
        have = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "execution_records" not in have:
            return
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(execution_records)"))}
        if "surface" in cols:
            return
        conn.execute(text("DROP TABLE IF EXISTS execution_records_new"))
        conn.execute(text(
            "CREATE TABLE execution_records_new ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "block_id INTEGER NOT NULL REFERENCES blocks (id), "
            "version VARCHAR NOT NULL, "
            "surface VARCHAR NOT NULL DEFAULT '', "
            "status VARCHAR NOT NULL DEFAULT 'pending', "
            "claimed_by VARCHAR NOT NULL DEFAULT '', "
            "claimed_by_key_id INTEGER, "
            "implemented_by_key_id INTEGER, "
            "reason TEXT NOT NULL DEFAULT '', "
            "results_json TEXT NOT NULL DEFAULT '[]', "
            "verification_json TEXT NOT NULL DEFAULT '[]', "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "CONSTRAINT uq_exec_block_version_surface UNIQUE (block_id, version, surface))"
        ))
        conn.execute(text(
            "INSERT INTO execution_records_new (id, block_id, version, surface, status, claimed_by, "
            "claimed_by_key_id, implemented_by_key_id, reason, results_json, verification_json, created_at, updated_at) "
            "SELECT id, block_id, version, '', status, claimed_by, claimed_by_key_id, implemented_by_key_id, "
            "reason, results_json, verification_json, created_at, updated_at FROM execution_records"
        ))
        conn.execute(text("DROP TABLE execution_records"))
        conn.execute(text("ALTER TABLE execution_records_new RENAME TO execution_records"))


def create_schema() -> None:
    """建表 + 增量迁移（幂等）。只动表结构，不写任何数据；种子数据（预置角色、执行记录补齐）
    在上层的 ``bootstrap.init_db`` 里做，这样本模块不必反过来依赖它们。"""
    _rename_legacy_tables()
    Base.metadata.create_all(get_engine())
    _rebuild_execution_records()
    _ensure_columns()
