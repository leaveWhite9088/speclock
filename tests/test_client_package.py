"""客户端包下载接口：GET /api/v1/agent/client-package[/{filename}]。

speclock 包不上 PyPI，开发 agent 从本站下载 wheel 安装。两个接口都不鉴权
（wheel 不含敏感数据）；文件来自仓库根目录 dist/（部署时 pip wheel 构建），
测试用 monkeypatch 把 CLIENT_DIST_DIR 指到临时目录。"""

from __future__ import annotations

import pytest

from speclock import api_agent

WHEEL_NAME = "speclock-0.1.0-py3-none-any.whl"


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    monkeypatch.setattr(api_agent, "CLIENT_DIST_DIR", tmp_path)
    return tmp_path


def write_wheel(dist, name=WHEEL_NAME):
    p = dist / name
    p.write_bytes(b"fake wheel bytes")
    return p


def test_client_package_info(env, dist):
    write_wheel(dist)
    r = env["client"].get("/api/v1/agent/client-package")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "speclock"
    assert body["version"] == "0.1.0"
    assert body["filename"] == WHEEL_NAME
    assert body["url"].endswith(f"/api/v1/agent/client-package/{WHEEL_NAME}")
    assert body["install_command"] == f'pip install "speclock @ {body["url"]}"'


def test_client_package_no_auth_required(env, dist):
    """不带 X-API-Key 也可用（agent 装包时还没有 key）。"""
    write_wheel(dist)
    assert env["client"].get("/api/v1/agent/client-package").status_code == 200
    assert env["client"].get(f"/api/v1/agent/client-package/{WHEEL_NAME}").status_code == 200


def test_client_package_picks_latest_wheel(env, dist):
    write_wheel(dist, "speclock-0.1.0-py3-none-any.whl")
    write_wheel(dist, "speclock-0.2.0-py3-none-any.whl")
    body = env["client"].get("/api/v1/agent/client-package").json()
    assert body["filename"] == "speclock-0.2.0-py3-none-any.whl"
    assert body["version"] == "0.2.0"


def test_client_package_not_built(env, dist):
    """dist/ 里没有 wheel 时 404，提示尚未构建。"""
    r = env["client"].get("/api/v1/agent/client-package")
    assert r.status_code == 404
    assert "尚未构建" in r.json()["detail"]


def test_install_url_respects_x_forwarded_proto(env, dist):
    """站点走 nginx https 反代，scheme 以 X-Forwarded-Proto 为准。"""
    write_wheel(dist)
    r = env["client"].get(
        "/api/v1/agent/client-package", headers={"X-Forwarded-Proto": "https"}
    )
    assert r.json()["url"].startswith("https://")


def test_download_wheel(env, dist):
    write_wheel(dist)
    r = env["client"].get(f"/api/v1/agent/client-package/{WHEEL_NAME}")
    assert r.status_code == 200
    assert r.content == b"fake wheel bytes"
    assert "attachment" in r.headers["content-disposition"]
    assert WHEEL_NAME in r.headers["content-disposition"]


def test_download_invalid_filename(env, dist):
    """不匹配 wheel 文件名模式一律 400（防路径穿越）。"""
    write_wheel(dist)
    for bad in ("foo.txt", f"{WHEEL_NAME}.bak", "speclock-0.1.0.tar.gz"):
        r = env["client"].get(f"/api/v1/agent/client-package/{bad}")
        assert r.status_code == 400, bad


def test_download_missing_wheel(env, dist):
    """文件名合法但 dist/ 里不存在 → 404。"""
    write_wheel(dist)
    r = env["client"].get("/api/v1/agent/client-package/speclock-9.9.9-py3-none-any.whl")
    assert r.status_code == 404
