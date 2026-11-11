"""网页免登录：每个项目一把绑定项目的只读 key；网页只看得到这一个项目；自动发放的边界；viewer 只能读。"""

from __future__ import annotations

import json

import pytest

from speclock_config import WEB_KEY_FILE, home, read_web_key
from speclock_core import ApiKey, Role, SessionLocal, ensure_web_key, retire_global_web_key
from tests.conftest import make_key, publish_v1
from tests.test_projects import _make_project_with_published_block

LOCAL = {"host": "127.0.0.1:8000"}


@pytest.fixture()
def web_home(env, tmp_path, monkeypatch):
    h = tmp_path / ".speclock"
    home.write_home(h, 8000)
    monkeypatch.setenv("SPECLOCK_HOME", str(h))
    return h


def _viewer(env, web_home, project_id=None):
    pid = project_id or env["project_id"]
    return {"X-API-Key": ensure_web_key(pid, web_home)}


def test_ensure_web_key_creates_a_project_bound_viewer_key_once(env, web_home):
    pid = env["project_id"]
    key = ensure_web_key(pid, web_home)
    assert key and key.startswith("human-") and read_web_key(web_home, pid) == key
    assert ensure_web_key(pid, web_home) == key  # 再来一次不换
    db = SessionLocal()
    try:
        rows = db.query(ApiKey).filter(ApiKey.label == "web").all()
        assert len(rows) == 1 and rows[0].role.name == "viewer" and rows[0].project_id == pid
    finally:
        db.close()
    ignored = (web_home / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "web-keys/" in ignored and WEB_KEY_FILE in ignored


def test_each_project_gets_its_own_key(env, web_home):
    other, _, _ = _make_project_with_published_block(env, "项目B", "B模块")
    a, b = ensure_web_key(env["project_id"], web_home), ensure_web_key(other, web_home)
    assert a != b


def test_a_deleted_web_key_is_replaced(env, web_home):
    old = ensure_web_key(env["project_id"], web_home)
    db = SessionLocal()
    db.query(ApiKey).filter(ApiKey.label == "web").delete()
    db.commit()
    db.close()
    new = ensure_web_key(env["project_id"], web_home)
    assert new and new != old


def test_the_old_global_web_key_is_retired(env, web_home):
    (web_home / WEB_KEY_FILE).write_text("human-old\n", encoding="utf-8")
    db = SessionLocal()
    from speclock_core import hash_key, key_hint

    role = db.query(Role).filter(Role.name == "viewer").first()
    db.add(ApiKey(key=hash_key("human-old"), hint=key_hint("human-old"), prefix="human", role_id=role.id,
                  project_id=None, label="web"))
    db.commit()
    db.close()
    retire_global_web_key(web_home)
    assert not (web_home / WEB_KEY_FILE).exists()
    assert env["client"].get("/api/v1/me", headers={"X-API-Key": "human-old"}).status_code == 401


def test_session_endpoint_gives_the_key_only_to_local_same_origin(env, web_home):
    c = env["client"]
    r = c.get("/api/v1/web/session", headers=LOCAL)  # 只有一个项目：不用指明
    assert r.status_code == 200 and r.json() == {"key": ensure_web_key(env["project_id"], web_home),
                                                 "project_id": env["project_id"]}
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/web/session", headers={"host": "evil.example.com"}).status_code == 403  # DNS 重绑定
    assert c.get("/api/v1/web/session", headers={**LOCAL, "sec-fetch-site": "cross-site"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://evil.example.com"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://127.0.0.1:8000"}).status_code == 200


def test_session_with_several_projects_needs_the_project(env, web_home):
    c = env["client"]
    other, _, _ = _make_project_with_published_block(env, "项目B", "B模块")
    r = c.get("/api/v1/web/session", headers=LOCAL)
    assert r.status_code == 422 and r.json()["code"] == "web_project_required"
    r = c.get(f"/api/v1/web/session?project_id={other}", headers=LOCAL)
    assert r.status_code == 200 and r.json()["project_id"] == other
    assert c.get("/api/v1/web/session?project_id=999", headers=LOCAL).status_code == 404
    names = c.get("/api/v1/web/projects", headers=LOCAL).json()
    assert {p["id"] for p in names} == {env["project_id"], other} and all(set(p) == {"id", "name"} for p in names)
    assert c.get("/api/v1/web/projects", headers={"host": "evil.example.com"}).status_code == 403


def test_session_404_without_a_speclock_dir(env, tmp_path, monkeypatch):
    monkeypatch.delenv("SPECLOCK_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert env["client"].get("/api/v1/web/session", headers=LOCAL).status_code == 404


def test_the_web_key_sees_only_its_own_project(env, web_home):
    """网页用绑定项目的 key 画界面：别的项目的结构、审核单、活动、密钥、搜索一概看不到。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    other, other_block, other_cap = _make_project_with_published_block(env, "项目B", "B项目的机密模块")
    # B 项目里也有它自己的 key、审核单
    c.post("/api/v1/keys", json={"role": "executor-agent", "label": "B的执行", "project_id": other}, headers=h)
    v = _viewer(env, web_home)

    assert [p["id"] for p in c.get("/api/v1/projects", headers=v).json()] == [env["project_id"]]
    tree = c.get("/api/v1/tree", headers=v).json()
    assert [p["id"] for p in tree] == [env["project_id"]]
    assert "B项目的机密模块" not in json.dumps(tree, ensure_ascii=False)
    assert c.get(f"/api/v1/blocks/{other_block}", headers=v).status_code == 404
    assert c.get(f"/api/v1/capabilities/{other_cap}", headers=v).status_code == 404
    assert all(w["block_id"] != other_block for w in c.get("/api/v1/work", headers=v).json())
    assert "B项目的机密模块" not in c.get("/api/v1/search?q=机密", headers=v).text
    keys = c.get("/api/v1/keys", headers=v).json()
    assert keys and {k["project_id"] for k in keys} == {env["project_id"]}
    assert all(k["label"] != "B的执行" for k in keys)
    activity = c.get("/api/v1/activity?limit=500", headers=v).json()
    assert activity and all(f":{other_block}" not in a["target"] for a in activity)
    assert all("项目B" not in json.dumps(a, ensure_ascii=False) for a in activity)
    # 超级管理员看得到全部
    root = make_key(env, "admin", project_bound=False)
    assert len(c.get("/api/v1/tree", headers=root).json()) == 2
    assert len(c.get("/api/v1/activity?limit=500", headers=root).json()) > len(activity)


def test_viewer_can_read_what_the_web_shows_but_cannot_write(env, web_home):
    c = env["client"]
    v = _viewer(env, web_home)
    for path in ("/api/v1/me", "/api/v1/index", "/api/v1/work", "/api/v1/change-requests", "/api/v1/activity",
                 "/api/v1/keys", "/api/v1/roles", "/api/v1/permissions", "/api/v1/projects", "/api/v1/search?q=x"):
        assert c.get(path, headers=v).status_code == 200, path
    assert c.post("/api/v1/keys", json={"role": "admin", "label": "x", "via": "cli"}, headers=v).status_code == 403
    assert c.post("/api/v1/change-requests/1/approve", json={}, headers=v).status_code in (403, 404, 422)
    assert c.delete("/api/v1/keys/1", headers=v).status_code == 403
    assert c.delete(f"/api/v1/blocks/{env['block_id']}", headers=v).status_code == 403


def test_viewer_is_a_builtin_role_and_admin_gets_key_read(env):
    db = SessionLocal()
    try:
        perms = {r.name: set(json.loads(r.permissions_json)) for r in db.query(Role).all()}
    finally:
        db.close()
    assert perms["viewer"] == {"spec.read", "cr.read", "exec.read", "audit.read", "key.read"}
    assert "key.read" in perms["admin"] and "key.read" not in perms["requirements-agent"]
