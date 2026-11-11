"""版本历史读取：模块 / 小业务的 history 接口、版本状态、项目隔离；预置角色残留权限清理。"""

from __future__ import annotations

import json

from speclock_core import SessionLocal
from speclock_core import Role
from speclock_core import seed_roles
from tests.conftest import (
    APIS_V2_MINOR,
    change_block,
    commit,
    make_key,
    open_cr,
    publish_v1,
)


def _two_versions(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    return change_block(env, env["block_id"], apis=APIS_V2_MINOR, note="加字段")


def test_block_history_lists_versions_oldest_first_with_status_and_trace(env):
    c = env["client"]
    v2 = _two_versions(env)
    r = c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=env["agent"])
    assert r.status_code == 200
    rows = r.json()
    assert [x["version"] for x in rows] == ["1.0.0", v2["version"]]
    first, last = rows
    assert (first["status"], first["superseded_by"]) == ("deprecated", v2["version"])
    assert (last["status"], last["superseded_by"]) == ("current", None)
    assert first["level"] == "initial" and last["level"] == v2["level"]
    assert first["cr_id"] is None and last["cr_id"] and last["commit_id"]
    assert last["change_note"] == "加字段"
    assert any("extra_note" in a for a in last["delta"]["added"])
    assert "events" not in last and "work_id" not in last  # 执行进展不在历史里


def test_capability_history_has_manifests(env):
    c = env["client"]
    _two_versions(env)
    rows = c.get(f"/api/v1/capabilities/{env['capability_id']}/history", headers=env["agent"]).json()
    assert [x["version"] for x in rows] == ["1.0.0", "1.1.0"]
    assert rows[0]["status"] == "deprecated" and rows[1]["status"] == "current"
    assert rows[1]["manifest"][str(env["block_id"])]["version"] == "1.1.0"
    assert rows[1]["triggered_by_block_id"] == env["block_id"] and rows[1]["cr_id"]


def test_history_needs_spec_read_and_hides_unpublished_and_archived(env):
    c = env["client"]
    scanner = make_key(env, "scanner-agent")
    assert c.get(f"/api/v1/blocks/{env['block_id']}/history").status_code == 401
    # 未发布：404
    assert c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=scanner).status_code == 404
    assert c.get(f"/api/v1/capabilities/{env['capability_id']}/history",
                 headers=scanner).status_code == 404
    publish_v1(c, env["human"], env["block_id"])
    assert c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=scanner).status_code == 200
    # 归档：对 Agent 不可见
    cr = open_cr(env)
    assert commit(env, cr, [{"op": "archive_block", "id": env["block_id"]}],
                  covers=["AC-1"]).status_code == 200
    assert c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=scanner).status_code == 404


def test_history_is_project_scoped(env):
    from tests.test_projects import _make_project_with_published_block

    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    pid_b, bid_b, doc_b = _make_project_with_published_block(env, "项目B", "B项目模块")
    r = c.post("/api/v1/keys", json={"role": "executor-agent", "project_id": pid_b}, headers=h)
    scoped = {"X-API-Key": r.json()["key"]}
    assert c.get(f"/api/v1/blocks/{bid_b}/history", headers=scoped).status_code == 200
    assert c.get(f"/api/v1/capabilities/{doc_b}/history", headers=scoped).status_code == 200
    assert c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=scoped).status_code == 404
    assert c.get(f"/api/v1/capabilities/{env['capability_id']}/history",
                 headers=scoped).status_code == 404
    # 管理端的版本列表同样做项目隔离
    assert c.get(f"/api/v1/blocks/{env['block_id']}/versions", headers=scoped).status_code == 404


def test_admin_version_lists_carry_status(env):
    c, h = env["client"], env["human"]
    v2 = _two_versions(env)
    rows = c.get(f"/api/v1/blocks/{env['block_id']}/versions", headers=h).json()
    assert [(x["version"], x["status"]) for x in rows] == [("1.0.0", "deprecated"), (v2["version"], "current")]
    assert rows[0]["superseded_by"] == v2["version"] and rows[1]["superseded_by"] is None
    caps = c.get(f"/api/v1/capabilities/{env['capability_id']}/versions", headers=h).json()
    assert [x["status"] for x in caps] == ["deprecated", "current"]


def test_history_pulls_are_audited(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    c.get(f"/api/v1/blocks/{env['block_id']}/history", headers=env["agent"])
    rows = c.get("/api/v1/activity", headers=env["human"]).json()
    assert f"block:{env['block_id']}/history" in [r["target"] for r in rows]


def test_mcp_exposes_history_tools():
    import inspect

    from speclock_mcp import server as mcp_server

    assert list(inspect.signature(mcp_server.get_block_history).parameters) == ["block_id"]
    assert list(inspect.signature(mcp_server.get_capability_history).parameters) == ["capability_id"]


# ---------- 残留权限清理 ----------


def test_seed_roles_prunes_permissions_that_no_longer_exist(env):
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.name == "admin").one()
        role.permissions_json = json.dumps(sorted([*json.loads(role.permissions_json), "ack.write", "spec.void"]))
        db.commit()
        seed_roles(db)
        db.refresh(role)
        have = set(json.loads(role.permissions_json))
        assert "ack.write" not in have and "spec.void" not in have
        assert {"spec.read", "key.manage", "exec.verify"} <= have
    finally:
        db.close()
