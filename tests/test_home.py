"""``.speclock/`` 的查找与 init：跟项目走、跟电脑走，数据不进源码目录。"""

from __future__ import annotations

import pytest

from speclock_core import db as dbmod
from speclock_core import init_home
from speclock_config import home


@pytest.fixture()
def clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECLOCK_HOME", raising=False)
    monkeypatch.setenv("SPECLOCK_GLOBAL_HOME", str(tmp_path / "global" / ".speclock"))
    yield
    dbmod.configure(__import__("os").environ["SPECLOCK_DB_URL"])  # 还原测试库


def test_find_walks_up_like_git(tmp_path, clean_env):
    proj = tmp_path / "proj"
    (proj / "speclock" / "src").mkdir(parents=True)
    home.write_home(proj / ".speclock", 4321)
    # 源码克隆在项目里面：从克隆目录里面运行，也能找到项目根的 .speclock
    assert home.find_home(proj / "speclock" / "src") == proj / ".speclock"
    assert home.read_config(proj / ".speclock").port == 4321


def test_project_home_wins_over_global(tmp_path, clean_env):
    home.write_home(home.global_home(), home.GLOBAL_PORT)
    proj = tmp_path / "proj"
    proj.mkdir()
    assert home.find_home(proj) == home.global_home()  # 项目里没有 → 用电脑级
    home.write_home(proj / ".speclock", 4000)
    assert home.find_home(proj) == proj / ".speclock"  # 项目里有 → 用项目的


def test_env_overrides_and_missing_is_a_clear_error(tmp_path, clean_env, monkeypatch):
    assert home.find_home(tmp_path) is None
    with pytest.raises(home.NotInitialised, match="speclock init"):
        home.load_config(tmp_path)
    monkeypatch.setenv("SPECLOCK_HOME", str(tmp_path / "x"))
    assert home.find_home(tmp_path) == tmp_path / "x"


def test_init_project_creates_random_admin_key_once(tmp_path, clean_env):
    from speclock_core import hash_key
    from speclock_core import ApiKey, Project

    proj = tmp_path / "shop"
    proj.mkdir()
    cfg, key = init_home(proj)
    assert cfg.home == proj / ".speclock" and key and key.startswith("human-")
    assert (cfg.home / ".gitignore").read_text(encoding="utf-8").splitlines()[1] == "*.db"
    assert cfg.db_path.is_file() and not (proj / "speclock.db").exists()
    db = dbmod.SessionLocal()
    try:
        assert [k.key for k in db.query(ApiKey).filter(ApiKey.label == "admin").all()] == [hash_key(key)]  # 只存哈希
        assert db.query(ApiKey).filter(ApiKey.label == "web").count() == 1 and (cfg.home / "web.key").is_file()
        assert [p.name for p in db.query(Project).all()] == ["shop"]
    finally:
        db.close()
    # 再 init 一次：不会换 key，也不会再给明文
    cfg2, again = init_home(proj)
    assert again is None and cfg2.port == cfg.port


def test_init_global_uses_the_fixed_cold_port(tmp_path, clean_env):
    cfg, key = init_home(tmp_path, glob=True)
    assert cfg.home == home.global_home() and cfg.port == home.GLOBAL_PORT and key
    assert cfg.port not in (8000, 8080, 3000, 5000)


def test_project_init_picks_a_free_port(tmp_path, clean_env):
    (tmp_path / "a").mkdir()
    cfg, _ = init_home(tmp_path / "a")
    assert 1024 < cfg.port < 65536


def test_default_url_follows_the_discovered_home(tmp_path, clean_env, monkeypatch):
    monkeypatch.delenv("SPECLOCK_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    assert home.default_url().endswith(str(home.GLOBAL_PORT))
    home.write_home(tmp_path / ".speclock", 5555)
    assert home.default_url() == "http://127.0.0.1:5555"
    monkeypatch.setenv("SPECLOCK_URL", "http://example:1/")
    assert home.default_url() == "http://example:1"


def test_new_admin_issues_another_admin_key_when_the_first_is_lost(tmp_path, clean_env):
    from speclock_core import hash_key
    from speclock_core import ApiKey

    proj = tmp_path / "lost"
    proj.mkdir()
    _, first = init_home(proj)
    _, second = init_home(proj, new_admin=True)
    assert second and second != first
    db = dbmod.SessionLocal()
    try:
        for k in (first, second):
            assert db.query(ApiKey).filter(ApiKey.key == hash_key(k)).first().role.name == "admin"
    finally:
        db.close()
