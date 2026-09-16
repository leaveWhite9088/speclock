"""环境配置（speclock.toml 双环境一键切换）：加载与覆盖顺序。"""

from __future__ import annotations


def _write_config(tmp_path, body: str) -> str:
    p = tmp_path / "speclock.toml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_load_settings_local_and_server(tmp_path, monkeypatch):
    from speclock.settings import load_settings

    path = _write_config(
        tmp_path,
        'active = "local"\n'
        '[local]\ndb_url = "sqlite:///local.db"\nhost = "127.0.0.1"\nport = 8000\npublic_url = ""\n'
        '[server]\ndb_url = "sqlite:////opt/speclock/prod.db"\nhost = "0.0.0.0"\nport = 9000\n'
        'public_url = "http://81.70.39.239:9000"\n',
    )
    monkeypatch.setenv("SPECLOCK_CONFIG", path)
    monkeypatch.delenv("SPECLOCK_ENV", raising=False)

    s = load_settings()
    assert (s.env, s.host, s.port, s.db_url) == ("local", "127.0.0.1", 8000, "sqlite:///local.db")
    assert s.public_url == ""

    # SPECLOCK_ENV 覆盖 active，不改文件即切换
    monkeypatch.setenv("SPECLOCK_ENV", "server")
    s = load_settings()
    assert (s.env, s.host, s.port) == ("server", "0.0.0.0", 9000)
    assert s.public_url == "http://81.70.39.239:9000"
    assert s.db_url == "sqlite:////opt/speclock/prod.db"


def test_load_settings_unknown_env_rejected(tmp_path, monkeypatch):
    import pytest

    from speclock.settings import load_settings

    path = _write_config(tmp_path, 'active = "prod"\n[local]\nport = 8000\n')
    monkeypatch.setenv("SPECLOCK_CONFIG", path)
    monkeypatch.delenv("SPECLOCK_ENV", raising=False)
    with pytest.raises(ValueError, match="prod"):
        load_settings()


def test_load_settings_missing_file_defaults(tmp_path, monkeypatch):
    from speclock.settings import load_settings

    monkeypatch.setenv("SPECLOCK_CONFIG", str(tmp_path / "nonexistent.toml"))
    monkeypatch.delenv("SPECLOCK_ENV", raising=False)
    s = load_settings()
    assert (s.env, s.host, s.port) == ("local", "127.0.0.1", 8000)
    assert s.public_url == "" and s.db_url.startswith("sqlite:///")


# 注：public_url 字段仍保留在配置中，但 MCP 接入页已由 Vue SPA 在浏览器侧
# 按 window.location.origin 生成配置（web/src/views/McpView.vue），服务端不再读取。
