"""网页免登录：网页用的是一把普通的、绑定项目的 viewer key（存成 key 文件，和其他 key 一样）；
网页只看得到这一个项目；自动发放的边界；viewer 只能读。"""

from __future__ import annotations

import json

import pytest

from speclock_config import home
from speclock_core import (
    ApiKey, Role, SessionLocal, ensure_web_key, ensure_web_keys, find_web_key, hash_key, key_hint,
    retire_legacy_web_keys,
)
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


def test_the_web_key_is_an_ordinary_project_bound_viewer_key_stored_like_the_others(env, web_home):
    pid = env["project_id"]
    key = ensure_web_key(pid, web_home)
    assert key and key.startswith("human-") and find_web_key(pid, web_home) == key
    assert ensure_web_key(pid, web_home) == key  # 再来一次不换
    db = SessionLocal()
    try:
        rows = db.query(ApiKey).filter(ApiKey.label == "web").all()
        assert len(rows) == 1 and rows[0].role.name == "viewer" and rows[0].project_id == pid
        file = web_home / "keys" / rows[0].key_file  # 和 Agent 的 key 一样存在 keys/ 里
        assert file.is_file() and file.read_text(encoding="utf-8").strip() == key
    finally:
        db.close()
    assert not (web_home / "web-keys").exists() and not (web_home / "web.key").exists()
    # 管理员列表里它和别的 key 一样：看得到、不含明文、带文件名
    listed = [k for k in env["client"].get("/api/v1/keys", headers=env["human"]).json() if k["label"] == "web"]
    assert listed and listed[0]["key_file"] and "key" not in listed[0]


def test_an_admin_created_viewer_key_works_for_the_web_too(env, web_home):
    r = env["client"].post("/api/v1/keys", json={"role": "viewer", "label": "只读", "project_id": env["project_id"]},
                           headers=env["human"])
    assert r.status_code == 201 and r.json()["key_file"] and "key" not in r.json() and "mcp_config" not in r.json()
    assert find_web_key(env["project_id"], web_home)  # 网页用它，不再另建


def test_creating_a_project_creates_its_web_key(env, web_home):
    root = make_key(env, "admin", project_bound=False)
    pid = env["client"].post("/api/v1/projects", json={"name": "新项目"}, headers=root).json()["id"]
    assert find_web_key(pid, web_home)
    r = env["client"].get(f"/api/v1/web/session?project_id={pid}", headers=LOCAL)
    assert r.status_code == 200 and r.json()["project_id"] == pid


def test_ensure_web_keys_fills_in_the_projects_without_one(env, web_home):
    pid = env["project_id"]
    assert find_web_key(pid, web_home) is None
    ensure_web_keys(web_home)
    assert find_web_key(pid, web_home)


def test_each_project_gets_its_own_key(env, web_home):
    other, _, _ = _make_project_with_published_block(env, "项目B", "B模块")
    a, b = ensure_web_key(env["project_id"], web_home), ensure_web_key(other, web_home)
    assert a != b


def test_a_revoked_web_key_is_not_silently_recreated_by_the_session_endpoint(env, web_home):
    old = ensure_web_key(env["project_id"], web_home)
    row = [k for k in env["client"].get("/api/v1/keys", headers=env["human"]).json() if k["label"] == "web"][0]
    assert env["client"].delete(f"/api/v1/keys/{row['id']}", headers=env["human"]).status_code == 200  # 管理员吊销
    assert env["client"].get("/api/v1/web/session", headers=LOCAL).status_code == 404  # 网页不会悄悄再建
    new = ensure_web_key(env["project_id"], web_home)  # 启动时的补齐才会重建
    assert new and new != old


def test_the_old_web_keys_are_retired(env, web_home):
    (web_home / "web.key").write_text("human-old", encoding="utf-8")
    (web_home / "web-keys").mkdir()
    (web_home / "web-keys" / "1.key").write_text("human-old2", encoding="utf-8")
    db = SessionLocal()
    role = db.query(Role).filter(Role.name == "viewer").first()
    for plain, pid in (("human-old", None), ("human-old2", env["project_id"])):  # 旧版：全局的 / 每项目一把存在 web-keys/
        db.add(ApiKey(key=hash_key(plain), hint=key_hint(plain), prefix="human", role_id=role.id,
                      project_id=pid, label="web"))
    db.commit()
    db.close()
    retire_legacy_web_keys(web_home)
    assert not (web_home / "web.key").exists() and not (web_home / "web-keys").exists()
    for plain in ("human-old", "human-old2"):
        assert env["client"].get("/api/v1/me", headers={"X-API-Key": plain}).status_code == 401


def test_session_endpoint_gives_the_key_only_to_local_same_origin(env, web_home):
    c = env["client"]
    ensure_web_key(env["project_id"], web_home)
    r = c.get("/api/v1/web/session", headers=LOCAL)  # 只有一个项目：不用指明
    assert r.status_code == 200 and r.json() == {"key": find_web_key(env["project_id"], web_home),
                                                 "project_id": env["project_id"]}
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/web/session", headers={"host": "evil.example.com"}).status_code == 403  # DNS 重绑定
    assert c.get("/api/v1/web/session", headers={**LOCAL, "sec-fetch-site": "cross-site"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://evil.example.com"}).status_code == 403
    assert c.get("/api/v1/web/session", headers={**LOCAL, "origin": "http://127.0.0.1:8000"}).status_code == 200


def test_session_with_several_projects_needs_the_project(env, web_home):
    c = env["client"]
    other, _, _ = _make_project_with_published_block(env, "项目B", "B模块")
    ensure_web_keys(web_home)
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
    assert c.delete(f"/api/v1/blocks/{env['block_id']}?cr_id=1", headers=v).status_code == 403


def test_viewer_is_a_builtin_role_and_admin_gets_key_read(env):
    db = SessionLocal()
    try:
        perms = {r.name: set(json.loads(r.permissions_json)) for r in db.query(Role).all()}
    finally:
        db.close()
    assert perms["viewer"] == {"spec.read", "cr.read", "exec.read", "audit.read", "key.read"}
    assert "key.read" in perms["admin"] and "key.read" not in perms["requirements-agent"]
