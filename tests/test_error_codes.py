"""错误码：detail 保持原样，另带稳定的 code；登记表和代码里实际使用的一致。"""

from __future__ import annotations

import re
from pathlib import Path

from speclock_core import ERROR_CODES, GENERIC_ERROR_CODES, ApiError
from tests.conftest import approve_cr, commit, cr_body, make_key, open_cr, publish_v1, qa_key, req_key

PACKAGES = Path(__file__).resolve().parents[1] / "packages"
OK_RESULT = {"results": [{"ac_id": "AC-1", "result": "pass", "evidence": "ok"}]}


def _code(r) -> str:
    body = r.json()
    assert set(body) == {"detail", "code"}, body
    return body["code"]


def test_registry_matches_the_code_that_uses_it():
    used: set[str] = set()
    for path in PACKAGES.rglob("*.py"):
        used |= set(re.findall(r'ApiError\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert used <= set(ERROR_CODES), f"代码里用了没登记的错误码：{used - set(ERROR_CODES)}"
    unused = set(ERROR_CODES) - used - set(GENERIC_ERROR_CODES.values())
    assert not unused, f"登记了但没有任何地方使用的错误码：{unused}"
    for code, (status, meaning) in ERROR_CODES.items():
        assert re.fullmatch(r"[a-z]+(_[a-z]+)*", code) and 400 <= status < 600 and meaning
    assert ApiError("cr_state_conflict", "x").status_code == 409


def test_missing_wrong_and_insufficient_keys(env):
    c = env["client"]
    r = c.get("/api/v1/me")
    assert r.status_code == 401 and _code(r) == "unauthenticated"
    r = c.get("/api/v1/me", headers={"X-API-Key": "human-nope"})
    assert r.status_code == 401 and _code(r) == "unauthenticated"
    r = c.post("/api/v1/keys", json={"role": "viewer"}, headers=env["agent"])
    assert r.status_code == 403 and _code(r) == "permission_denied"
    assert "缺少权限" in r.json()["detail"]  # 原来的中文 detail 不变


def test_not_found_unknown_path_and_wrong_method(env):
    c = env["client"]
    r = c.get("/api/v1/change-requests/9999", headers=req_key(env))
    assert r.status_code == 404 and _code(r) == "not_found" and r.json()["detail"] == "change request not found"
    r = c.get("/api/v1/no-such-endpoint", headers=env["human"])
    assert r.status_code == 404 and _code(r) == "not_found"
    r = c.delete("/api/v1/me", headers=env["human"])
    assert r.status_code == 405 and _code(r) == "method_not_allowed"


def test_validation_errors_have_a_code_for_both_kinds(env):
    c = env["client"]
    r = c.post("/api/v1/change-requests", json={"intent": "没有标题"}, headers=req_key(env))
    assert r.status_code == 422 and _code(r) == "validation_failed" and isinstance(r.json()["detail"], list)
    r = c.post("/api/v1/change-requests", json=cr_body(title="  "), headers=req_key(env))
    assert r.status_code == 422 and _code(r) == "validation_failed" and isinstance(r.json()["detail"], str)
    r = c.get("/api/v1/blocks/abc", headers=env["human"])
    assert r.status_code == 400 and _code(r) == "bad_request"


def test_change_request_state_conflicts(env):
    c, req = env["client"], req_key(env)
    cr = open_cr(env, approve=False)
    r = commit(env, cr, [], covers=["AC-1"], change_note="x")  # 还没批准就提交 Commit
    assert r.status_code == 409 and _code(r) == "cr_state_conflict"
    r = c.post(f"/api/v1/change-requests/{cr}/complete", headers=req)
    assert r.status_code == 409 and _code(r) == "cr_state_conflict"

    # 撤回、改动、重新提交后，旧的内容哈希不能再用来批准
    old_hash = c.get(f"/api/v1/change-requests/{cr}", headers=req).json()["content_hash"]
    c.post(f"/api/v1/change-requests/{cr}/withdraw", headers=req)
    c.put(f"/api/v1/change-requests/{cr}", json={"intent": "改了一点"}, headers=req)
    c.post(f"/api/v1/change-requests/{cr}/submit", headers=req)
    r = c.post(f"/api/v1/change-requests/{cr}/approve", json={"content_hash": old_hash}, headers=env["human"])
    assert r.status_code == 409 and _code(r) == "cr_content_changed"

    approve_cr(env, cr)
    r = c.post(f"/api/v1/change-requests/{cr}/withdraw", headers=req)  # 人批准过的不能撤回
    assert r.status_code == 409 and _code(r) == "cr_state_conflict"
    r = c.post(f"/api/v1/change-requests/{cr}/complete", headers=req)
    assert r.status_code == 409 and _code(r) == "cr_no_commits"
    ok = commit(env, cr, [{"op": "update_capability", "id": env["capability_id"], "summary": "摘要"}], covers=[])
    assert ok.status_code == 200, ok.text
    r = c.post(f"/api/v1/change-requests/{cr}/complete", headers=req)
    assert r.status_code == 409 and _code(r) == "cr_coverage_incomplete"
    assert r.json()["detail"]["missing"] == ["AC-1"]  # 带结构的 detail 原样保留


def test_supersede_target_must_be_approved(env):
    c, req = env["client"], req_key(env)
    draft = c.post("/api/v1/change-requests", json=cr_body(), headers=req).json()["id"]
    r = c.post("/api/v1/change-requests", json=cr_body(supersedes_id=draft), headers=req)
    assert r.status_code == 409 and _code(r) == "cr_supersede_invalid"


def test_only_the_draft_owner_can_edit_it(env):
    c = env["client"]
    mine = c.post("/api/v1/change-requests", json=cr_body(), headers=req_key(env)).json()["id"]
    second = make_key(env, "requirements-agent", label="二号")
    r = c.put(f"/api/v1/change-requests/{mine}", json={"intent": "抢着改"}, headers=second)
    assert r.status_code == 403 and _code(r) == "cr_not_owner"


def test_execution_conflicts(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    work = c.get("/api/v1/work", headers=env["agent"]).json()[0]["id"]
    r = c.post(f"/api/v1/work/{work}/implementation", json=OK_RESULT, headers=env["agent"])  # 没领取就提交
    assert r.status_code == 409 and _code(r) == "work_state_conflict"
    assert c.post(f"/api/v1/work/{work}/claim", headers=env["agent"]).status_code == 200
    r = c.post(f"/api/v1/work/{work}/claim", headers=env["agent"])
    assert r.status_code == 409 and _code(r) == "work_already_claimed"

    # 模块发布新版本后，旧版本上的记录被取代
    cr = open_cr(env)
    new_text = "# 数据采集模块\n\n改了背景，超过二十个字符的业务叙述内容。"
    ok = commit(env, cr, [{"op": "update_block", "id": env["block_id"], "content_md": new_text}], covers=["AC-1"])
    assert ok.status_code == 200, ok.text
    r = c.post(f"/api/v1/work/{work}/failed", json={"reason": "x"}, headers=env["agent"])
    assert r.status_code == 409 and _code(r) == "work_superseded"
    assert r.json()["detail"]["latest_work_id"] and "error" in r.json()["detail"]


def test_only_the_holder_acts_and_the_verifier_is_not_the_implementer(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    work = c.get("/api/v1/work", headers=env["agent"]).json()[0]["id"]
    c.post(f"/api/v1/work/{work}/claim", headers=env["agent"])
    other = make_key(env, "executor-agent", label="二号")
    r = c.post(f"/api/v1/work/{work}/failed", json={"reason": "不是我领的"}, headers=other)
    assert r.status_code == 403 and _code(r) == "work_not_holder"

    c.post(f"/api/v1/work/{work}/implementation", json=OK_RESULT, headers=env["agent"])
    r = c.post(f"/api/v1/work/{work}/verification", json=OK_RESULT, headers=env["agent"])
    # executor-agent 没有验收权限：这是权限问题，不是「验证者就是实现者」
    assert r.status_code == 403 and _code(r) == "permission_denied"
    r = c.post(f"/api/v1/work/{work}/verification", json=OK_RESULT, headers=qa_key(env))
    assert r.status_code == 200 and r.json()["status"] == "verified"


def test_the_verifier_who_is_also_the_implementer_is_refused(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    work = c.get("/api/v1/work", headers=env["human"]).json()[0]["id"]
    assert c.post(f"/api/v1/work/{work}/claim", headers=env["human"]).status_code == 200
    assert c.post(f"/api/v1/work/{work}/implementation", json=OK_RESULT, headers=env["human"]).status_code == 200
    r = c.post(f"/api/v1/work/{work}/verification", json=OK_RESULT, headers=env["human"])
    assert r.status_code == 403 and _code(r) == "work_verifier_is_implementer"


def test_archived_block_code(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr = open_cr(env)
    assert commit(env, cr, [{"op": "archive_block", "id": env["block_id"]}], covers=["AC-1"]).status_code == 200
    cr2 = open_cr(env)
    r = commit(env, cr2, [{"op": "update_block", "id": env["block_id"], "title": "改名"}], covers=["AC-1"])
    assert r.status_code == 409 and _code(r) == "block_archived"
    assert "第 1 条 op" in r.json()["detail"]  # Commit 里包了一层的错误也保留了 code
