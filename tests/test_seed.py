"""Seed 固定 dev key：编码阶段只发一把 admin key；默认固定、可环境变量覆盖、重复执行幂等。
密钥哈希化后，库里存的是明文的 SHA-256，测试断言哈希值。"""

from __future__ import annotations

from speclock import seed
from speclock.auth import hash_key
from speclock.db import SessionLocal, configure, init_db
from speclock.models import ApiKey, Block


def _run_seed(tmp_path, name="seed.db"):
    url = f"sqlite:///{tmp_path}/{name}"
    configure(url)
    init_db()
    seed.main()


def _keys():
    db = SessionLocal()
    keys = {k.key: k.role.name for k in db.query(ApiKey).all()}
    db.close()
    return keys


def _clear_env(monkeypatch):
    for name in ("SPECLOCK_ADMIN_KEY", "SPECLOCK_HUMAN_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_seed_creates_a_single_admin_key_by_default(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    _run_seed(tmp_path)
    assert _keys() == {hash_key(seed.DEFAULT_ADMIN_KEY): "admin"}


def test_seed_empty_creates_project_and_key_only(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr("sys.argv", ["seed", "--empty"])
    _run_seed(tmp_path, "empty.db")
    assert _keys() == {hash_key(seed.DEFAULT_ADMIN_KEY): "admin"}
    from speclock.models import Business, Project

    db = SessionLocal()
    assert (db.query(Project).count(), db.query(Business).count(), db.query(Block).count()) == (1, 0, 0)
    db.close()


def test_seed_env_override(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SPECLOCK_ADMIN_KEY", "human-prod-random-xxxx")
    _run_seed(tmp_path, "override.db")
    assert _keys() == {hash_key("human-prod-random-xxxx"): "admin"}


def test_seed_legacy_env_name_still_works(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SPECLOCK_HUMAN_KEY", "human-legacy-yyyy")
    _run_seed(tmp_path, "legacy.db")
    assert hash_key("human-legacy-yyyy") in _keys()


def test_seed_idempotent_reuses_keys(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    _run_seed(tmp_path, "idem.db")
    first = _keys()
    seed.main()  # 第二次执行：复用已有 key，不重复插入
    assert _keys() == first
    db = SessionLocal()
    assert db.query(ApiKey).count() == 1
    assert db.query(Block).count() == 8  # demo 数据不重复建
    db.close()


def test_mcp_exposes_approve_and_reject_but_they_need_evidence():
    """编码阶段 Agent 经 MCP 代人批准：批准工具必须带内容哈希与人的原话。"""
    import inspect

    from speclock import mcp_server

    sig = inspect.signature(mcp_server.approve_change_request)
    assert {"cr_id", "content_hash", "evidence"} <= set(sig.parameters)
    assert sig.parameters["evidence"].default is inspect.Parameter.empty  # 必填
    assert "reason" in inspect.signature(mcp_server.reject_change_request).parameters
