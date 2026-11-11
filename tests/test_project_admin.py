"""超级管理员与项目管理员：除超级管理员外所有 key 都必须绑定项目；项目管理员看得到本项目的全部动态，只管本项目。"""

from __future__ import annotations

import json

from tests.conftest import cr_body, make_key, open_cr, publish_v1

ROLES = ("requirements-agent", "executor-agent", "tester-agent", "scanner-agent", "project-admin", "reviewer", "viewer")


def _code(r) -> str:
    return r.json()["code"]


def _second_project(env) -> int:
    r = env["client"].post("/api/v1/projects", json={"name": "项目B"}, headers=env["human"])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(env, headers, **body):
    return env["client"].post("/api/v1/keys", json=body, headers=headers)


def _project_admin(env, project_id=None):
    r = _create(env, env["human"], role="project-admin", project_id=project_id or env["project_id"], label="主管")
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["key"]}


def test_every_key_except_the_global_admin_must_bind_a_project(env):
    h = env["human"]
    for role in ROLES:
        r = _create(env, h, role=role)
        assert r.status_code == 422 and _code(r) == "project_required", role
        r = _create(env, h, role=role, project_id=env["project_id"])
        assert r.status_code == 201 and r.json()["project_id"] == env["project_id"], role
    assert _create(env, h, role="admin").status_code == 201  # 只有超级管理员可以是全局的


def test_the_global_admin_creates_and_deletes_the_keys_of_any_project(env):
    c = env["client"]
    other = _second_project(env)
    root = make_key(env, "admin", project_bound=False)  # 全局超级管理员
    made = [_create(env, root, role=role, project_id=pid, label=f"{role}-{pid}")
            for pid in (env["project_id"], other) for role in ("project-admin", "reviewer", "executor-agent")]
    assert all(r.status_code == 201 for r in made)
    rows = c.get("/api/v1/keys", headers=root).json()
    assert {k["project_id"] for k in rows if k["label"].endswith(f"-{other}")} == {other}
    assert all(c.delete(f"/api/v1/keys/{r.json()['id']}", headers=root).status_code == 200 for r in made)


def test_project_admin_does_not_manage_keys_or_roles_or_projects(env):
    c = env["client"]
    pa = _project_admin(env)
    r = _create(env, pa, role="executor-agent", project_id=env["project_id"])
    assert r.status_code == 403 and _code(r) == "permission_denied"
    assert c.delete("/api/v1/keys/1", headers=pa).status_code == 403
    r = c.post("/api/v1/roles", json={"name": "x", "kind": "agent", "permissions": ["spec.read"]}, headers=pa)
    assert r.status_code == 403
    assert c.post("/api/v1/projects", json={"name": "偷建"}, headers=pa).status_code == 403
    # 只读得到本项目的 key
    other = _second_project(env)
    _create(env, env["human"], role="executor-agent", project_id=other, label="B的执行")
    rows = c.get("/api/v1/keys", headers=pa).json()
    assert rows and {k["project_id"] for k in rows} == {env["project_id"]}


def test_project_admin_sees_the_projects_dynamics_and_only_that_project(env):
    """主管要看到本项目的动态：卡点（blocked）、失败（failed）、待审批、活动日志；别的项目的看不到。"""
    c = env["client"]
    pa = _project_admin(env)
    publish_v1(c, env["human"], env["block_id"])
    work = c.get("/api/v1/work", headers=env["agent"]).json()[0]["id"]
    c.post(f"/api/v1/work/{work}/claim", headers=env["agent"])
    r = c.post(f"/api/v1/work/{work}/blocked", json={"reason": "口径没说清"}, headers=env["agent"])
    assert r.status_code == 200
    pending = open_cr(env, approve=False)  # 待审批

    blocked = c.get("/api/v1/work?status=blocked", headers=pa).json()
    assert [w["id"] for w in blocked] == [work] and blocked[0]["reason"] == "口径没说清"
    assert [x["id"] for x in c.get("/api/v1/change-requests?status=pending_review", headers=pa).json()] == [pending]
    activity = c.get("/api/v1/activity?limit=200", headers=pa).json()
    assert {"exec_blocked", "cr_submit"} <= {a["action"] for a in activity}

    # 别的项目里发生的事，主管一概看不到
    other = _second_project(env)
    glob = make_key(env, "requirements-agent", project_bound=False)
    theirs = c.post("/api/v1/change-requests", json=cr_body(project_id=other, title="B项目的机密单"), headers=glob).json()["id"]
    c.post(f"/api/v1/change-requests/{theirs}/submit", headers=glob)
    assert all(x["id"] != theirs for x in c.get("/api/v1/change-requests", headers=pa).json())
    assert c.get(f"/api/v1/change-requests/{theirs}", headers=pa).status_code == 404
    after = c.get("/api/v1/activity?limit=500", headers=pa).json()
    assert f"cr:{theirs}" not in json.dumps(after, ensure_ascii=False)


def test_project_admin_approves_only_its_own_projects_requests(env):
    c = env["client"]
    pa = _project_admin(env)
    cr = open_cr(env, approve=False)
    content_hash = c.get(f"/api/v1/change-requests/{cr}", headers=pa).json()["content_hash"]
    r = c.post(f"/api/v1/change-requests/{cr}/approve", json={"content_hash": content_hash}, headers=pa)
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_a_project_admin_does_not_count_as_the_last_super_admin(env):
    c, h = env["client"], env["human"]
    _project_admin(env)
    admin_keys = [k for k in c.get("/api/v1/keys", headers=h).json() if k["role"] == "admin"]
    assert len(admin_keys) == 1
    r = c.delete(f"/api/v1/keys/{admin_keys[0]['id']}", headers=h)  # 唯一的超级管理员：项目管理员不能顶替
    assert r.status_code == 409 and "超级管理员" in r.json()["detail"]
