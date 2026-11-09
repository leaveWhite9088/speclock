"""网页可被嵌入：CSP frame-ancestors、/embed.js、没有构建网页时的提示页。"""

from __future__ import annotations

import pytest

from speclock import home, main


def test_every_response_says_who_may_embed_the_page(env):
    r = env["client"].get("/api/v1/me", headers=env["human"])
    csp = r.headers["content-security-policy"]
    assert csp.startswith("frame-ancestors 'self'")
    assert "http://localhost:*" in csp and "http://127.0.0.1:*" in csp
    assert "[::1]" not in csp  # CSP 不认 IPv6 的方括号写法，写进去会让整条指令失效


def test_embed_js_is_served_without_a_key_and_exposes_the_api(env):
    r = env["client"].get("/embed.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "window.SpecLock" in r.text and "data-speclock" in r.text and "embed=1" in r.text


def test_config_can_widen_the_allowed_origins(tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    text = (h / "config.toml").read_text(encoding="utf-8")
    assert "embed_origins" in text  # 新建的配置里有这一项，方便改
    assert "http://localhost:*" in home.read_config(h).embed_origins  # 默认只有本机
    (h / "config.toml").write_text('port = 1\nembed_origins = ["https://my.app", "*"]\n', encoding="utf-8")
    assert home.read_config(h).embed_origins == ("https://my.app", "*")
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    assert home.embed_origins() == ("https://my.app", "*")


def test_without_a_built_web_the_root_explains_how_to_build_it(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "DIST_DIR", tmp_path / "no-dist")
    page = TestClient(main.create_app()).get("/")
    assert page.status_code == 200 and "npm run build" in page.text
