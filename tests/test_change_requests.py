"""审核单（CR）：状态机、提交即冻结、内容哈希、批准渠道留痕、驳回、取代、项目隔离。"""

from __future__ import annotations

from tests.conftest import (
    approve_cr,
    commit,
    cr_body,
    make_key,
    open_cr,
    req_key,
)

URL = "/api/v1/change-requests"


def _create(env, **over):
    r = env["client"].post(URL, json=cr_body(**over), headers=req_key(env))
    assert r.status_code == 201, r.text
    return r.json()


def _get(env, cr_id, headers=None):
    r = env["client"].get(f"{URL}/{cr_id}", headers=headers or env["human"])
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 创建与草稿 ----------


def test_create_draft_assigns_acceptance_ids(env):
    cr = _create(env, acceptance=[
        {"name": "甲", "detail": "验收甲的详述"}, {"name": "乙", "detail": "验收乙的详述"}])
    assert cr["status"] == "draft" and cr["content_hash"] == ""
    assert [a["id"] for a in cr["acceptance"]] == ["AC-1", "AC-2"]
    assert cr["project_id"] == env["project_id"]  # 项目绑定的 key 可省略 project_id
    assert cr["created_by"].startswith("agent-")


def test_draft_can_be_incomplete_but_cannot_submit(env):
    cr = _create(env, intent="", expected_outcome="", acceptance=[])
    r = env["client"].post(f"{URL}/{cr['id']}/submit", headers=req_key(env))
    assert r.status_code == 422
    assert len(r.json()["detail"]["missing"]) == 3


def test_draft_edit_keeps_acceptance_ids(env):
    cr = _create(env, acceptance=[{"name": "甲", "detail": "验收甲的详述"}])
    r = env["client"].put(f"{URL}/{cr['id']}", headers=req_key(env), json={
        "intent": "改了动机",
        "acceptance": [{"id": "AC-1", "name": "甲改名", "detail": "验收甲的详述"},
                       {"name": "乙", "detail": "新增的验收"}]})
    assert r.status_code == 200
    out = r.json()
    assert out["intent"] == "改了动机"
    assert [(a["id"], a["name"]) for a in out["acceptance"]] == [("AC-1", "甲改名"), ("AC-2", "乙")]


def test_obsolete_and_acceptance_validation(env):
    c = env["client"]
    r = c.post(URL, json=cr_body(obsolete=["  "]), headers=req_key(env))
    assert r.status_code == 422
    r = c.post(URL, json=cr_body(acceptance=[{"name": "x", "detail": " "}]), headers=req_key(env))
    assert r.status_code == 422
    r = c.post(URL, json=cr_body(title="  "), headers=req_key(env))
    assert r.status_code == 422


def test_global_key_must_name_project(env):
    glob = make_key(env, "requirements-agent", project_bound=False)
    r = env["client"].post(URL, json=cr_body(), headers=glob)
    assert r.status_code == 422
    r = env["client"].post(URL, json=cr_body(project_id=env["project_id"]), headers=glob)
    assert r.status_code == 201
    r = env["client"].post(URL, json=cr_body(project_id=999), headers=glob)
    assert r.status_code == 404


# ---------- 提交即冻结 / 内容哈希 ----------


def test_submit_freezes_content_and_hashes(env):
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    cr = _get(env, cr_id)
    assert cr["status"] == "pending_review" and len(cr["content_hash"]) == 64
    r = c.put(f"{URL}/{cr_id}", json={"intent": "偷偷改"}, headers=req_key(env))
    assert r.status_code == 409  # 冻结
    assert _get(env, cr_id)["intent"] != "偷偷改"


def test_withdraw_unfreezes_and_new_hash_invalidates_old_approval(env):
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    old_hash = _get(env, cr_id)["content_hash"]
    r = c.post(f"{URL}/{cr_id}/withdraw", headers=req_key(env))
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["content_hash"] == ""
    c.put(f"{URL}/{cr_id}", json={"intent": "补充了动机"}, headers=req_key(env))
    c.post(f"{URL}/{cr_id}/submit", headers=req_key(env))
    new_hash = _get(env, cr_id)["content_hash"]
    assert new_hash != old_hash
    # 人拿着旧版本的哈希来批准：批准的不是他现在看到的那一版 → 409
    r = c.post(f"{URL}/{cr_id}/approve", json={"content_hash": old_hash}, headers=env["human"])
    assert r.status_code == 409
    assert _get(env, cr_id)["status"] == "pending_review"
    approve_cr(env, cr_id)


def test_cannot_withdraw_or_edit_after_approval(env):
    c = env["client"]
    cr_id = open_cr(env)
    assert c.post(f"{URL}/{cr_id}/withdraw", headers=req_key(env)).status_code == 409
    assert c.put(f"{URL}/{cr_id}", json={"title": "x"}, headers=req_key(env)).status_code == 409
    assert c.post(f"{URL}/{cr_id}/submit", headers=req_key(env)).status_code == 409


# ---------- 批准 / 驳回 ----------


def test_approve_records_decision_and_channel(env):
    cr_id = open_cr(env, approve=False)
    out = approve_cr(env, cr_id, via="cli", note="看过了")
    assert out["status"] == "approved"
    assert out["decided_by"].startswith("human-")
    assert (out["decision_via"], out["decision_note"]) == ("cli", "看过了")
    assert out["decided_at"] is not None


def test_natural_language_approval_requires_evidence(env):
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    h = _get(env, cr_id)["content_hash"]
    r = c.post(f"{URL}/{cr_id}/approve",
               json={"content_hash": h, "via": "natural_language"}, headers=env["human"])
    assert r.status_code == 422
    r = c.post(f"{URL}/{cr_id}/approve", headers=env["human"], json={
        "content_hash": h, "via": "natural_language", "evidence": "同意，就按这个来"})
    assert r.status_code == 200
    out = r.json()
    assert out["decision_via"] == "natural_language" and out["decision_evidence"] == "同意，就按这个来"


def test_invalid_via_rejected(env):
    cr_id = open_cr(env, approve=False)
    h = _get(env, cr_id)["content_hash"]
    r = env["client"].post(f"{URL}/{cr_id}/approve",
                           json={"content_hash": h, "via": "telepathy"}, headers=env["human"])
    assert r.status_code == 422


def test_cannot_approve_a_draft_or_twice(env):
    c = env["client"]
    draft = _create(env)
    r = c.post(f"{URL}/{draft['id']}/approve", json={"content_hash": ""}, headers=env["human"])
    assert r.status_code == 409
    cr_id = open_cr(env)
    h = _get(env, cr_id)["content_hash"]
    r = c.post(f"{URL}/{cr_id}/approve", json={"content_hash": h}, headers=env["human"])
    assert r.status_code == 409


def test_reject_requires_reason_and_is_terminal(env):
    c = env["client"]
    cr_id = open_cr(env, approve=False)
    r = c.post(f"{URL}/{cr_id}/reject", json={"reason": "  "}, headers=env["human"])
    assert r.status_code == 422
    r = c.post(f"{URL}/{cr_id}/reject", headers=env["human"],
               json={"reason": "验收条件没写清楚", "via": "api"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # 需求 Agent 读得到驳回理由，据此另开新单
    seen = _get(env, cr_id, req_key(env))
    assert seen["decision_note"] == "验收条件没写清楚" and seen["decided_by"].startswith("human-")
    # 终态：不能再批准 / 撤回 / 改 / 提交 Commit
    assert c.post(f"{URL}/{cr_id}/withdraw", headers=req_key(env)).status_code == 409
    assert c.put(f"{URL}/{cr_id}", json={"title": "x"}, headers=req_key(env)).status_code == 409
    r = commit(env, cr_id, [{"op": "archive_block", "id": env["block_id"]}])
    assert r.status_code == 409


# ---------- 取代 ----------


def test_supersede_approved_cr(env):
    c = env["client"]
    old = open_cr(env)
    new = open_cr(env, approve=False, supersedes_id=old)
    assert _get(env, old)["status"] == "approved"  # 新单批准之前旧单仍有效
    approve_cr(env, new)
    old_out = _get(env, old)
    assert (old_out["status"], old_out["superseded_by_id"]) == ("superseded", new)
    # 被取代的审核单不能再提交 Commit
    r = commit(env, old, [{"op": "archive_block", "id": env["block_id"]}])
    assert r.status_code == 409


def test_supersede_requires_approved_target(env):
    c = env["client"]
    pending = open_cr(env, approve=False)
    r = c.post(URL, json=cr_body(supersedes_id=pending), headers=req_key(env))
    assert r.status_code == 409
    r = c.post(URL, json=cr_body(supersedes_id=9999), headers=req_key(env))
    assert r.status_code == 422


# ---------- 读取 / 过滤 / 项目隔离 ----------


def test_list_filter_by_status(env):
    a = open_cr(env, approve=False)
    b = open_cr(env)
    c = env["client"]
    pending = c.get(URL, params={"status": "pending_review"}, headers=env["human"]).json()
    approved = c.get(URL, params={"status": "approved"}, headers=env["human"]).json()
    assert [x["id"] for x in pending] == [a]
    assert [x["id"] for x in approved] == [b]
    assert c.get(URL, params={"status": "bogus"}, headers=env["human"]).status_code == 422
    assert "commits" not in pending[0]  # 列表是摘要，详情才带 Commit


def test_executor_can_read_crs_to_learn_why(env):
    cr_id = open_cr(env)
    seen = env["client"].get(f"{URL}/{cr_id}", headers=env["agent"])
    assert seen.status_code == 200 and seen.json()["intent"]


def test_project_isolation(env):
    c = env["client"]
    other = c.post("/api/v1/projects", json={"name": "别的项目"}, headers=env["human"]).json()["id"]
    cr_id = open_cr(env)
    other_agent = make_key(env, "requirements-agent", project_bound=False)
    # 绑定到别的项目的 key 看不到、也动不了本项目的审核单（404，不泄露存在）
    r = c.post("/api/v1/keys", json={"role": "requirements-agent", "project_id": other},
               headers=env["human"])
    bound_other = {"X-API-Key": r.json()["key"]}
    assert c.get(f"{URL}/{cr_id}", headers=bound_other).status_code == 404
    assert c.post(f"{URL}/{cr_id}/withdraw", headers=bound_other).status_code == 404
    assert c.get(URL, headers=bound_other).json() == []
    # 在别的项目建单要显式指明项目，且不能越权建到本项目
    r = c.post(URL, json=cr_body(project_id=env["project_id"]), headers=bound_other)
    assert r.status_code == 404
    # 全局 key 可以跨项目
    assert c.get(f"{URL}/{cr_id}", headers=other_agent).status_code == 200


def test_audit_trail_of_cr_lifecycle(env):
    cr_id = open_cr(env)
    actions = [a["action"] for a in env["client"].get(
        "/api/v1/activity", params={"limit": 200}, headers=env["human"]).json()
        if a["target"] == f"cr:{cr_id}"]
    assert {"cr_create", "cr_submit", "cr_approve"} <= set(actions)
