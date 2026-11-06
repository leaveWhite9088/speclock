"""老库迁移：Domain/Document 改名为 Business/Capability（表、外键列、doc_type 列）。

做法：先用当前模型建库并写入数据，再用 SQL 把它还原成旧结构（domains /
documents(+doc_type) / document_versions，domain_id / document_id 列），
然后跑 init_db，断言数据完整保留、结构已迁到新名字且服务仍可用。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from sqlalchemy import text

from speclock.db import SessionLocal, configure, get_engine, init_db
from speclock.models import Block, Business, Capability, Project


def _make_legacy_db(path: str) -> None:
    url = f"sqlite:///{path}"
    configure(url)
    init_db()
    db = SessionLocal()
    p = Project(name="旧项目")
    db.add(p)
    db.flush()
    b = Business(project_id=p.id, name="运营")
    db.add(b)
    db.flush()
    cap = Capability(business_id=b.id, title="经营日报", current_version="1.2.0")
    db.add(cap)
    db.flush()
    db.add(Block(capability_id=cap.id, title="数据采集模块"))
    db.commit()
    db.close()
    get_engine().dispose()

    con = sqlite3.connect(path)
    con.execute("ALTER TABLE businesses RENAME TO domains")
    con.execute("ALTER TABLE capabilities RENAME TO documents")
    con.execute("ALTER TABLE capability_versions RENAME TO document_versions")
    con.execute("ALTER TABLE documents RENAME COLUMN business_id TO domain_id")
    con.execute("ALTER TABLE documents DROP COLUMN summary")
    con.execute("ALTER TABLE documents ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'business'")
    con.execute("ALTER TABLE document_versions RENAME COLUMN capability_id TO document_id")
    con.execute("ALTER TABLE blocks RENAME COLUMN capability_id TO document_id")
    con.commit()
    con.close()


def test_legacy_tables_are_renamed_and_data_is_kept():
    original = os.environ["SPECLOCK_DB_URL"]
    path = os.path.join(tempfile.mkdtemp(prefix="speclock-legacy-"), "legacy.db")
    try:
        _make_legacy_db(path)

        configure(f"sqlite:///{path}")
        init_db()
        init_db()  # 幂等：重复执行不报错、不重复迁移

        with get_engine().connect() as conn:
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"businesses", "capabilities", "capability_versions"} <= tables
            assert not ({"domains", "documents", "document_versions"} & tables)

            cap_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(capabilities)"))}
            assert "business_id" in cap_cols and "summary" in cap_cols
            assert "domain_id" not in cap_cols and "doc_type" not in cap_cols
            block_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(blocks)"))}
            assert "capability_id" in block_cols and "document_id" not in block_cols

        db = SessionLocal()
        cap = db.query(Capability).one()
        assert (cap.title, cap.current_version, cap.summary) == ("经营日报", "1.2.0", "")
        assert cap.business.name == "运营"
        assert cap.business.project.name == "旧项目"
        assert [b.title for b in cap.blocks] == ["数据采集模块"]
        # 迁移后仍可正常写入
        db.add(Capability(business_id=cap.business_id, title="售罄率报表"))
        db.commit()
        db.close()
    finally:
        get_engine().dispose()
        configure(original)
