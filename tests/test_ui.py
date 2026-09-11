"""UI 页面级 key 校验：非法/缺失 key 一律重定向登录页，登录页带提示。"""

from __future__ import annotations

import pytest

from tests.conftest import publish_v1

UI_PAGES = [
    "/ui",
    "/ui/blocks/1",
    "/ui/blocks/1/view",
    "/ui/blocks/1/diff",
    "/ui/documents/1",
    "/ui/proposals",
    "/ui/acks",
]


@pytest.mark.parametrize("page", UI_PAGES)
def test_ui_pages_redirect_without_key(env, page):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(page, follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("/ui/login")


@pytest.mark.parametrize("page", UI_PAGES)
def test_ui_pages_redirect_with_unknown_or_agent_key(env, page):
    publish_v1(env["client"], env["human"], env["block_id"])
    for bad in ("human-deadbeefdeadbeef", env["agent"]["X-API-Key"]):
        r = env["client"].get(f"{page}?key={bad}", follow_redirects=False)
        assert r.status_code in (302, 307), f"{page} accepted {bad}"
        assert "/ui/login" in r.headers["location"]


@pytest.mark.parametrize("page", UI_PAGES)
def test_ui_pages_ok_with_valid_human_key(env, page):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"{page}?key={env['human']['X-API-Key']}")
    assert r.status_code == 200, f"{page}: {r.status_code}"


def test_login_page_shows_error_hint(env):
    r = env["client"].get("/ui/login?error=1")
    assert r.status_code == 200
    assert "无效" in r.text
    r = env["client"].get("/ui/login")
    assert "无效" not in r.text
