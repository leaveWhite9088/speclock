"""网页免登录：只读 key 的准备、自动发放的边界、viewer 角色只能读。"""

from __future__ import annotations

import json

import pytest

from speclock_config import home
from speclock_core import SessionLocal
from speclock_core import ApiKey, Role
from speclock_config import WEB_KEY_FILE, read_web_key
from speclock_core import ensure_web_key

LOCAL = {"host": "127.0.0.1:8000"}


@pytest.fixture()
def web_home(env, tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    return h


def test_ensure_web_key_creates_a_viewer_key_once(env, web_home):
    key = ensure_web_key(web_home)
    assert key and key.startswith("human-") and read_web_key(web_home) == key
    assert ensure_web_key(web_home) == key  # 再来一次不换
    db = SessionLocal()
    try:
        rows = db.query(ApiKey).filter(ApiKey.label == "web").all()
        assert len(rows) == 1 and rows[0].role.name == "viewer"
    finally:
        db.close()
    assert WEB_KEY_FILE in (web_home / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_a_deleted_web_key_is_replaced(env, web_home):
    old = ensure_web_key(web_home)
    db = SessionLocal()
    db.query(ApiKey).filter(ApiKey.label == "web").delete()
    db.commit()
    db.close()
    new = ensure_web_key(web_home)
    assert new and new != old


def test_session_endpoint_gives_the_key_only_to_local_same_origin(env, web_home):
    c = env["client"]
    key = ensure_web_key(web_home)
    r = c.get("/api/v1/web/session", headers=LOCAL)
    assert r.status_code == 200 and r.json() == {"key": key} and r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/web/session", headers={"host": "evil.example.com"}).status_code == 403  # DNS 重绑定
    assert c.get("/api/v1/web/session", headers={**LOCAL, "sec-fetch-site": "cross-site"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://evil.example.com"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://127.0.0.1:8000"}).status_code == 200


def test_session_endpoint_404_without_a_key(env, tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    assert env["client"].get("/api/v1/web/session", headers=LOCAL).status_code == 404


def test_viewer_can_read_what_the_web_shows_but_cannot_write(env, web_home):
    c = env["client"]
    v = {"X-API-Key": ensure_web_key(web_home)}
    for path in ("/api/v1/me", "/api/v1/index", "/api/v1/work", "/api/v1/change-requests", "/api/v1/activity",
                 "/api/v1/keys", "/api/v1/roles", "/api/v1/permissions", "/api/v1/projects", "/api/v1/search?q=x"):
        assert c.get(path, headers=v).status_code == 200, path
    assert c.post("/api/v1/keys", json={"role": "admin", "label": "x", "via": "cli"}, headers=v).status_code == 403
    assert c.post("/api/v1/change-requests/1/approve", json={}, headers=v).status_code in (403, 404, 422)
    assert c.delete("/api/v1/keys/1", headers=v).status_code == 403


def test_viewer_is_a_builtin_role_and_admin_gets_key_read(env):
    db = SessionLocal()
    try:
        perms = {r.name: set(json.loads(r.permissions_json)) for r in db.query(Role).all()}
    finally:
        db.close()
    assert perms["viewer"] == {"spec.read", "cr.read", "exec.read", "audit.read", "key.read"}
    assert "key.read" in perms["admin"] and "key.read" not in perms["requirements-agent"]
