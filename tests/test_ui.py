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


# ---------- 全站返回按钮 / 最近一次变更 / 单版本友好提示 ----------


@pytest.mark.parametrize("page", UI_PAGES)
def test_every_page_has_back_button(env, page):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(f"{page}?key={env['human']['X-API-Key']}")
    assert r.status_code == 200
    assert "← 返回上一页" in r.text and "history.back()" in r.text


def test_login_page_has_no_back_button(env):
    r = env["client"].get("/ui/login")
    assert "history.back()" not in r.text


def test_view_page_latest_diff_button(env):
    c, h = env["client"], env["human"]
    hk = h["X-API-Key"]
    publish_v1(c, h, env["block_id"])
    # 只有一个版本：按钮置灰并提示
    r = c.get(f"/ui/blocks/{env['block_id']}/view?key={hk}")
    assert "最近一次变更" in r.text
    assert "暂无历史版本" in r.text
    assert "btn-latest-diff\" disabled" in r.text or "disabled" in r.text
    # 发布第二版后：按钮跳到 1.0.0 → 1.1.0
    from tests.conftest import APIS_V2_MINOR

    c.put(f"/api/v1/blocks/{env['block_id']}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{env['block_id']}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    r = c.get(f"/ui/blocks/{env['block_id']}/view?key={hk}")
    assert "from=1.0.0&to=1.1.0" in r.text
    assert "暂无历史版本" not in r.text


def test_tree_page_latest_diff_link(env):
    c, h = env["client"], env["human"]
    hk = h["X-API-Key"]
    publish_v1(c, h, env["block_id"])
    # 单版本模块没有「最近 diff」链接
    assert "最近 diff" not in c.get(f"/ui?key={hk}").text
    from tests.conftest import APIS_V2_MINOR

    c.put(f"/api/v1/blocks/{env['block_id']}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{env['block_id']}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    r = c.get(f"/ui?key={hk}")
    assert "最近 diff" in r.text
    assert f"/ui/blocks/{env['block_id']}/diff" in r.text


def test_diff_page_single_version_friendly_message(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = env["client"].get(
        f"/ui/blocks/{env['block_id']}/diff?key={env['human']['X-API-Key']}"
    )
    assert r.status_code == 200
    assert "暂无可对比的历史版本" in r.text


def test_diff_page_defaults_to_last_two_versions(env):
    c, h = env["client"], env["human"]
    hk = h["X-API-Key"]
    publish_v1(c, h, env["block_id"])
    from tests.conftest import APIS_V2_MINOR

    c.put(f"/api/v1/blocks/{env['block_id']}", json={"apis": APIS_V2_MINOR}, headers=h)
    c.post(f"/api/v1/blocks/{env['block_id']}/publish",
           json={"change_note": "v2", "fastTrack": True}, headers=h)
    r = c.get(f"/ui/blocks/{env['block_id']}/diff?key={hk}")
    assert r.status_code == 200
    assert "@1.0.0 → @1.1.0" in r.text
