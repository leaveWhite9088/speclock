"""角色与权限：预置角色、自定义角色、权限映射可改、人类专属权限、防锁死、/me。"""

from __future__ import annotations

from speclock import permissions as perms
from tests.conftest import make_key, open_cr, publish_v1, req_key


def _roles(env):
    r = env["client"].get("/api/v1/roles", headers=env["human"])
    assert r.status_code == 200, r.text
    return {x["name"]: x for x in r.json()}


def test_preset_roles_exist_and_are_builtin(env):
    roles = _roles(env)
    assert {"admin", "reviewer", "requirements-agent", "executor-agent", "scanner-agent"} <= set(roles)
    assert all(roles[n]["builtin"] for n in roles)
    assert set(roles["admin"]["permissions"]) == set(perms.PERMISSIONS)
    assert "cr.approve" in roles["reviewer"]["permissions"]
    assert "cr.approve" not in roles["requirements-agent"]["permissions"]
    assert roles["requirements-agent"]["kind"] == "agent" and roles["reviewer"]["kind"] == "human"
    # 初始 human / agent key 回填到了 admin / executor-agent
    assert roles["admin"]["key_count"] == 1 and roles["executor-agent"]["key_count"] == 1


def test_permission_catalog_marks_human_only(env):
    cat = {p["name"]: p for p in env["client"].get("/api/v1/permissions", headers=env["human"]).json()}
    assert set(cat) == set(perms.PERMISSIONS)
    assert cat["cr.approve"]["human_only"] is True and cat["spec.read"]["human_only"] is False


def test_whoami(env):
    c = env["client"]
    me = c.get("/api/v1/me", headers=env["human"]).json()
    assert (me["kind"], me["role"], me["project_id"]) == ("human", "admin", env["project_id"])
    assert "cr.approve" in me["permissions"]
    me = c.get("/api/v1/me", headers=env["agent"]).json()
    assert (me["kind"], me["role"]) == ("agent", "executor-agent")
    assert me["permissions"] == ["ack.write", "cr.read", "spec.read"]
    assert c.get("/api/v1/me").status_code == 401


def test_key_prefix_follows_role_kind(env):
    c = env["client"]
    for role, prefix in (("admin", "human-"), ("reviewer", "human-"), ("scanner-agent", "agent-")):
        r = c.post("/api/v1/keys", json={"role": role}, headers=env["human"])
        assert r.status_code == 201 and r.json()["key"].startswith(prefix)
        assert r.json()["role"] == role and r.json()["prefix"] == prefix[:-1]
    assert c.post("/api/v1/keys", json={"role": "nope"}, headers=env["human"]).status_code == 404
    keys = c.get("/api/v1/keys", headers=env["human"]).json()
    assert all("role" in k for k in keys)


# ---------- 自定义角色 ----------


def test_custom_role_end_to_end(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    r = c.post("/api/v1/roles", headers=h, json={
        "name": "auditor", "kind": "agent", "description": "只读审计",
        "permissions": ["spec.read", "cr.read", "spec.read"]})
    assert r.status_code == 201
    assert r.json()["permissions"] == ["cr.read", "spec.read"] and r.json()["builtin"] is False

    key = make_key(env, "auditor")
    assert c.get("/api/v1/index", headers=key).status_code == 200
    assert c.get("/api/v1/change-requests", headers=key).status_code == 200
    assert c.post(f"/api/v1/blocks/{env['block_id']}/ack", json={"version": "1.0.0"},
                  headers=key).status_code == 403


def test_role_validation(env):
    c, h = env["client"], env["human"]
    base = {"name": "x", "kind": "agent", "permissions": []}
    # agent 类角色挂不上人类专属权限——Agent 永远批准不了审核单
    for p in ("cr.approve", "spec.void", "project.manage", "key.manage"):
        r = c.post("/api/v1/roles", headers=h, json={**base, "permissions": [p]})
        assert r.status_code == 422 and "人类专属" in r.json()["detail"], p
    # 人类角色可以
    assert c.post("/api/v1/roles", headers=h,
                  json={**base, "kind": "human", "permissions": ["cr.approve"]}).status_code == 201
    assert c.post("/api/v1/roles", headers=h,
                  json={**base, "name": "y", "permissions": ["made.up"]}).status_code == 422
    assert c.post("/api/v1/roles", headers=h, json={**base, "name": "9bad"}).status_code == 422
    assert c.post("/api/v1/roles", headers=h, json={**base, "kind": "robot"}).status_code == 422
    assert c.post("/api/v1/roles", headers=h, json={**base, "name": "admin"}).status_code == 409


def test_role_permissions_are_editable_even_for_presets(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    scanner = make_key(env, "scanner-agent")
    assert c.get("/api/v1/change-requests", headers=scanner).status_code == 403
    rid = _roles(env)["scanner-agent"]["id"]
    r = c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": ["spec.read", "cr.read"]})
    assert r.status_code == 200
    assert c.get("/api/v1/change-requests", headers=scanner).status_code == 200  # 立即生效
    r = c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": ["spec.read", "cr.approve"]})
    assert r.status_code == 422  # 预置的 agent 角色也不能挂人类专属权限
    # 把读权限撤掉 → key 立即 403
    c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": []})
    assert c.get("/api/v1/index", headers=scanner).status_code == 403


def test_requirements_role_without_commit_write_cannot_commit(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    cr_id = open_cr(env)
    rid = _roles(env)["requirements-agent"]["id"]
    perms_now = _roles(env)["requirements-agent"]["permissions"]
    c.put(f"/api/v1/roles/{rid}", headers=h,
          json={"permissions": [p for p in perms_now if p != "commit.write"]})
    r = c.post(f"/api/v1/change-requests/{cr_id}/commits", headers=req_key(env),
               json={"ops": [{"op": "archive_block", "id": env["block_id"]}]})
    assert r.status_code == 403 and "commit.write" in r.json()["detail"]


def test_delete_role_rules(env):
    c, h = env["client"], env["human"]
    roles = _roles(env)
    assert c.delete(f"/api/v1/roles/{roles['admin']['id']}", headers=h).status_code == 409  # 预置不可删
    rid = c.post("/api/v1/roles", headers=h, json={
        "name": "tmp", "kind": "agent", "permissions": ["spec.read"]}).json()["id"]
    key = c.post("/api/v1/keys", json={"role": "tmp"}, headers=h).json()
    assert c.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 409  # 仍有 key 在用
    c.delete(f"/api/v1/keys/{key['id']}", headers=h)
    assert c.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 200
    assert c.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 404


# ---------- 防锁死 ----------


def test_cannot_strip_key_manage_from_the_last_admin_role(env):
    c, h = env["client"], env["human"]
    rid = _roles(env)["admin"]["id"]
    r = c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": ["spec.read"]})
    assert r.status_code == 409 and "key.manage" in r.json()["detail"]
    # 有另一把拥有 key.manage 的 human key 之后就可以改
    other = make_key(env, "admin")
    assert other
    assert c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": ["spec.read"]}).status_code == 409
    # （两把 key 都绑在 admin 角色上，去掉权限会让两把同时失效，仍然拒绝）
    custom = c.post("/api/v1/roles", headers=h, json={
        "name": "ops", "kind": "human", "permissions": ["key.manage"]}).json()
    c.post("/api/v1/keys", json={"role": "ops"}, headers=h)
    assert custom["permissions"] == ["key.manage"]
    assert c.put(f"/api/v1/roles/{rid}", headers=h, json={"permissions": ["spec.read"]}).status_code == 200


def test_last_admin_key_cannot_be_deleted(env):
    c, h = env["client"], env["human"]
    admin_key = next(k for k in c.get("/api/v1/keys", headers=h).json() if k["role"] == "admin")
    assert c.delete(f"/api/v1/keys/{admin_key['id']}", headers=h).status_code == 409
    # 审核人 key 不算管理员，可以随便删
    rev = c.post("/api/v1/keys", json={"role": "reviewer"}, headers=h).json()
    assert c.delete(f"/api/v1/keys/{rev['id']}", headers=h).status_code == 200
    backup = c.post("/api/v1/keys", json={"role": "admin"}, headers=h).json()
    assert backup["key"]
    assert c.delete(f"/api/v1/keys/{admin_key['id']}", headers=h).status_code == 200


def test_reviewer_cannot_manage_keys_or_roles(env):
    c = env["client"]
    rev = make_key(env, "reviewer")
    for method, path, body in (("GET", "/api/v1/keys", None), ("GET", "/api/v1/roles", None),
                               ("GET", "/api/v1/permissions", None),
                               ("POST", "/api/v1/roles", {"name": "z", "kind": "human"})):
        r = c.request(method, path, headers=rev, **({"json": body} if body else {}))
        assert r.status_code == 403, (method, path)
