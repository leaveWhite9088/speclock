"""Seed 固定 dev key：默认固定、可环境变量覆盖、重复执行幂等。
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
    keys = {k.prefix: k.key for k in db.query(ApiKey).all()}
    db.close()
    return keys


def test_seed_uses_fixed_dev_keys_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECLOCK_HUMAN_KEY", raising=False)
    monkeypatch.delenv("SPECLOCK_AGENT_KEY", raising=False)
    _run_seed(tmp_path)
    keys = _keys()
    assert keys["human"] == hash_key(seed.DEFAULT_HUMAN_KEY)
    assert keys["agent"] == hash_key(seed.DEFAULT_AGENT_KEY)


def test_seed_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECLOCK_HUMAN_KEY", "human-prod-random-xxxx")
    monkeypatch.setenv("SPECLOCK_AGENT_KEY", "agent-prod-random-yyyy")
    _run_seed(tmp_path, "override.db")
    keys = _keys()
    assert keys["human"] == hash_key("human-prod-random-xxxx")
    assert keys["agent"] == hash_key("agent-prod-random-yyyy")


def test_seed_idempotent_reuses_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECLOCK_HUMAN_KEY", raising=False)
    monkeypatch.delenv("SPECLOCK_AGENT_KEY", raising=False)
    _run_seed(tmp_path, "idem.db")
    first = _keys()
    seed.main()  # 第二次执行：复用已有 key，不重复插入
    second = _keys()
    assert first == second
    db = SessionLocal()
    assert db.query(ApiKey).count() == 2
    assert db.query(Block).count() == 8  # demo 数据不重复建
    db.close()
