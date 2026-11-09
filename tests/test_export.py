"""导出与备份：文本快照稳定可进 git、完整备份可恢复、不会误删别的目录。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from speclock import exporter, home
from speclock.db import SessionLocal
from tests.conftest import publish_v1


@pytest.fixture()
def cfg(env, tmp_path):
    """一个真实的 .speclock/，其数据库是一份带了模块的拷贝（测试库本身的备份）。"""
    publish_v1(env["client"], env["human"], env["block_id"])
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    c = home.read_config(h)
    src = sqlite3.connect(str(__import__("os").environ["SPECLOCK_DB_URL"].removeprefix("sqlite:///")))
    dest = sqlite3.connect(str(c.db_path))
    src.backup(dest)
    dest.close()
    src.close()
    return c


def test_export_writes_readable_markdown_and_spec_json(env, tmp_path):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = tmp_path / "export"
    db = SessionLocal()
    try:
        stats = exporter.export_spec(db, out)
    finally:
        db.close()
    assert stats["blocks"] >= 1 and stats["projects"] >= 1
    assert (out / "index.md").is_file() and (out / "README.md").is_file()
    blocks = [p for p in out.rglob("*.md") if "change-requests" not in p.parts and p.name not in ("README.md", "index.md")]
    assert blocks
    text = blocks[0].read_text(encoding="utf-8")
    assert "## 业务规则" in text and "## 验收条件" in text and "## API" in text and "1.0.0" in text
    data = json.loads((out / "spec.json").read_text(encoding="utf-8"))
    block = data["projects"][0]["businesses"][0]["capabilities"][0]["blocks"][0]
    assert block["version"] == "1.0.0" and block["rules"] and block["acceptance"]


def test_export_is_stable_between_runs(env, tmp_path):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = tmp_path / "export"
    snapshots = []
    for _ in range(2):
        db = SessionLocal()
        try:
            exporter.export_spec(db, out)
        finally:
            db.close()
        snapshots.append({str(p.relative_to(out)): p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file()})
    assert snapshots[0] == snapshots[1]  # 没有时间戳，重复导出内容一字不差（git diff 干净）


def test_export_refuses_a_non_empty_foreign_directory(env, tmp_path):
    foreign = tmp_path / "my-docs"
    foreign.mkdir()
    (foreign / "important.txt").write_text("别删我", encoding="utf-8")
    db = SessionLocal()
    try:
        with pytest.raises(FileExistsError):
            exporter.export_spec(db, foreign)
    finally:
        db.close()
    assert (foreign / "important.txt").exists()


def test_reexport_drops_files_of_things_that_no_longer_exist(env, tmp_path):
    out = tmp_path / "export"
    db = SessionLocal()
    try:
        exporter.export_spec(db, out)
        (out / "stale.md").write_text("旧的", encoding="utf-8")
        exporter.export_spec(db, out)
    finally:
        db.close()
    assert not (out / "stale.md").exists()


def test_backup_and_restore_roundtrip(cfg, tmp_path):
    backup = exporter.backup_db(cfg, tmp_path / "b" / "copy.db")
    assert backup.is_file()
    with pytest.raises(FileExistsError):
        exporter.backup_db(cfg, backup)  # 不覆盖已有备份
    # 弄坏当前库，再恢复
    cfg.db_path.write_bytes(b"garbage")
    kept = exporter.restore_db(cfg, backup)
    assert kept is not None and kept.read_bytes() == b"garbage"  # 原来的库改名留着
    check = sqlite3.connect(str(cfg.db_path))
    assert check.execute("SELECT count(*) FROM blocks").fetchone()[0] >= 1
    check.close()


def test_restore_rejects_non_speclock_files_and_a_running_service(cfg, tmp_path, monkeypatch):
    other = tmp_path / "other.db"
    sqlite3.connect(str(other)).execute("CREATE TABLE t(x)").connection.close()
    with pytest.raises(ValueError, match="不是 SpecLock"):
        exporter.restore_db(cfg, other)
    with pytest.raises(FileNotFoundError):
        exporter.restore_db(cfg, tmp_path / "missing.db")
    monkeypatch.setattr(exporter, "_service_running", lambda c: True)
    good = exporter.backup_db(cfg, tmp_path / "good.db")
    with pytest.raises(RuntimeError, match="还在运行"):
        exporter.restore_db(cfg, good)
