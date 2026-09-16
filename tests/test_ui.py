"""SPA 托管：web/dist 存在时 / 与前端路由 fallback 到 index.html；
/api/ 下未注册的路径仍返回 JSON 404，不会被 fallback 吃掉。"""

from __future__ import annotations

from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

needs_dist = pytest.mark.skipif(not DIST.is_dir(), reason="web/dist 未构建")
needs_no_dist = pytest.mark.skipif(DIST.is_dir(), reason="web/dist 已构建，fallback 生效")


@needs_dist
def test_root_serves_spa_index(env):
    r = env["client"].get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="app"' in r.text  # Vue 挂载点


@needs_dist
@pytest.mark.parametrize("path", ["/proposals", "/blocks/1", "/documents/1/edit"])
def test_deep_links_fall_back_to_index(env, path):
    r = env["client"].get(path)
    assert r.status_code == 200
    assert 'id="app"' in r.text


@needs_dist
def test_built_assets_are_served(env):
    asset = next((DIST / "assets").iterdir())
    r = env["client"].get(f"/assets/{asset.name}")
    assert r.status_code == 200


@needs_dist
@pytest.mark.parametrize("path", ["/ui", "/ui/login", "/ui/mcp"])
def test_legacy_ui_paths_fall_back_to_spa(env, path):
    """旧 Jinja 页面路由已删除；带 dist 时这些路径由 SPA 接管（Vue router 处理）。"""
    r = env["client"].get(path)
    assert r.status_code == 200
    assert 'id="app"' in r.text


@needs_no_dist
@pytest.mark.parametrize("path", ["/", "/ui", "/ui/login"])
def test_no_dist_is_pure_json_api(env, path):
    """dist 未构建（纯 API 部署 / 测试环境）：无 SPA 可服务，一律 JSON 404。"""
    r = env["client"].get(path)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_unknown_api_path_returns_json_404(env):
    """catch-all 不得吞掉 API 的 404。"""
    r = env["client"].get("/api/v1/nonexistent")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Not Found"}


def test_registered_api_routes_unaffected_by_fallback(env):
    """已注册的 API 路由优先于 catch-all：无 key 时仍是 JSON 401 而非 index.html。"""
    r = env["client"].get("/api/v1/tree")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
