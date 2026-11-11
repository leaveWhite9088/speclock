"""超级管理员与项目管理员：Agent key、项目管理员的 key 必须绑定项目；项目管理员只管本项目。"""

from __future__ import annotations

from tests.conftest import cr_body, make_key, open_cr


def _code(r) -> str:
    return r.json()["code"]


def _second_project(env) -> int:
    r = env["client"].post("/api/v1/projects", json={"name": "项目B"}, headers=env["human"])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(env, headers, **body):
    return env["client"].post("/api/v1/keys", json=body, headers=headers)


def test_agent_and_project_admin_keys_must_bind_a_project(env):
    h = env["human"]
    for role in ("requirements-agent", "executor-agent", "tester-agent", "scanner-agent", "project-admin"):
        r = _create(env, h, role=role)
        assert r.status_code == 422 and _code(r) == "project_required", role
        assert _create(env, h, role=role, project_id=env["project_id"]).status_code == 201, role
    assert _create(env, h, role="admin").status_code == 201  # 超级管理员可以是全局的
    assert _create(env, h, role="reviewer").status_code == 201  # 其他人类角色不受影响


def test_project_admin_manages_only_its_own_project(env):
    c, h = env["client"], env["human"]
    other = _second_project(env)
    pa = {"X-API-Key": _create(env, h, role="project-admin", project_id=env["project_id"], label="主管").json()["key"]}
    foreign = _create(env, h, role="executor-agent", project_id=other, label="B的执行").json()

    # 建 key：默认落在自己的项目；别的项目当作不存在
    mine = _create(env, pa, role="executor-agent", label="我的执行")
    assert mine.status_code == 201 and mine.json()["project_id"] == env["project_id"]
    assert _create(env, pa, role="executor-agent", project_id=other).status_code == 404
    # 建不出带 project.manage 的角色（超级管理员）
    r = _create(env, pa, role="admin", project_id=env["project_id"])
    assert r.status_code == 403 and _code(r) == "super_admin_required"

    # 只看得到、删得掉本项目的 key
    rows = c.get("/api/v1/keys", headers=pa).json()
    assert rows and {k["project_id"] for k in rows} == {env["project_id"]}
    assert c.delete(f"/api/v1/keys/{foreign['id']}", headers=pa).status_code == 404
    assert c.delete(f"/api/v1/keys/{mine.json()['id']}", headers=pa).status_code == 200

    # 角色是全局配置，项目也不归它管
    r = c.post("/api/v1/roles", json={"name": "x", "kind": "agent", "permissions": ["spec.read"]}, headers=pa)
    assert r.status_code == 403 and _code(r) == "super_admin_required"
    r = c.post("/api/v1/projects", json={"name": "偷建"}, headers=pa)
    assert r.status_code == 403 and _code(r) == "permission_denied"


def test_project_admin_approves_only_its_own_projects_requests(env):
    c, h = env["client"], env["human"]
    pa = {"X-API-Key": _create(env, h, role="project-admin", project_id=env["project_id"]).json()["key"]}
    cr = open_cr(env, approve=False)  # 本项目 pending_review 的审核单
    content_hash = c.get(f"/api/v1/change-requests/{cr}", headers=pa).json()["content_hash"]
    r = c.post(f"/api/v1/change-requests/{cr}/approve", json={"content_hash": content_hash}, headers=pa)
    assert r.status_code == 200 and r.json()["status"] == "approved"

    other = _second_project(env)
    glob = make_key(env, "requirements-agent", project_bound=False)  # 升级前就有的全局 key，能给项目 B 开单
    theirs = c.post("/api/v1/change-requests", json=cr_body(project_id=other), headers=glob)
    assert theirs.status_code == 201, theirs.text
    assert c.get(f"/api/v1/change-requests/{theirs.json()['id']}", headers=pa).status_code == 404


def test_a_project_admin_does_not_count_as_the_last_super_admin(env):
    c, h = env["client"], env["human"]
    _create(env, h, role="project-admin", project_id=env["project_id"])
    admin_keys = [k for k in c.get("/api/v1/keys", headers=h).json() if k["role"] == "admin"]
    assert len(admin_keys) == 1
    r = c.delete(f"/api/v1/keys/{admin_keys[0]['id']}", headers=h)  # 唯一的超级管理员：项目管理员不能顶替
    assert r.status_code == 409 and "超级管理员" in r.json()["detail"]
