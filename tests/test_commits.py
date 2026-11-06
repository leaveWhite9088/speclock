"""Commit：已批准审核单下的原子写入——ops、$ref、跨 Block / Capability、回滚、覆盖检查、溯源。"""

from __future__ import annotations

from tests.conftest import (
    ACCEPTANCE_V1,
    APIS_V1,
    RULES_V1,
    approve_cr,
    commit,
    cr_body,
    make_key,
    open_cr,
    publish_v1,
    req_key,
)

CR = "/api/v1/change-requests"
BG = "# 新模块\n\n这是一段超过二十个字符的业务背景与流程叙述。"


def _new_block_op(capability, title="新模块", ref=None, **over):
    op = {"op": "create_block", "capability": capability, "title": title, "summary": title,
          "content_md": BG, "rules": RULES_V1, "apis": APIS_V1, "acceptance": ACCEPTANCE_V1}
    if ref:
        op["ref"] = ref
    op.update(over)
    return op


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _versions(env, block_id=None):
    return env["client"].get(
        f"/api/v1/blocks/{block_id or env['block_id']}/versions", headers=env["human"]).json()


# ---------- 门槛：权限与审核单状态 ----------


def test_commit_requires_commit_write_permission(env):
    cr_id = open_cr(env)
    r = env["client"].post(f"{CR}/{cr_id}/commits", headers=env["agent"],
                           json={"ops": [{"op": "archive_block", "id": 1}]})
    assert r.status_code == 403


def test_commit_requires_approved_cr(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    ops = [{"op": "archive_block", "id": env["block_id"]}]
    draft = env["client"].post(CR, json=cr_body(), headers=req_key(env)).json()["id"]
    pending = open_cr(env, approve=False)
    for cr_id in (draft, pending):
        r = commit(env, cr_id, ops)
        assert r.status_code == 409 and "approved" in r.json()["detail"]
    assert env["client"].get(
        f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).status_code == 200


# ---------- update_block ----------


def test_update_block_publishes_and_traces_back_to_cr(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr_id = open_cr(env)
    r = commit(env, cr_id, [{"op": "update_block", "id": env["block_id"],
                             "content_md": "# 数据采集模块\n\n只是把背景叙述写清楚了一些，业务没变。"}],
               covers=["AC-1"], change_note="澄清背景")
    out = _ok(r)
    assert out["commit_id"] and out["seq"] == 1 and out["covers"] == ["AC-1"]
    b = out["blocks"][0]
    assert (b["version"], b["level"], b["created"]) == ("1.0.1", "patch", False)
    assert out["capability_versions"] == [
        {"capability_id": env["capability_id"], "version": "1.0.1", "level": "patch"}]

    # 溯源：版本 → Commit → 审核单；审核单 → Commit → 版本
    v = _versions(env)[-1]
    assert (v["cr_id"], v["commit_id"], v["change_note"]) == (cr_id, out["commit_id"], "澄清背景")
    assert _versions(env)[0]["cr_id"] is None  # 示例数据直接发布，没有审核单
    agent_view = c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).json()
    assert agent_view["cr_id"] == cr_id and agent_view["commit_id"] == out["commit_id"]
    cr = c.get(f"{CR}/{cr_id}", headers=env["agent"]).json()
    assert cr["commits"][0]["result"]["blocks"][0]["version"] == "1.0.1"
    assert cr["coverage"] == {"covered": ["AC-1"], "missing": []}
    caps = c.get(f"/api/v1/capabilities/{env['capability_id']}/versions", headers=env["human"]).json()
    assert caps[-1]["cr_id"] == cr_id and caps[-1]["commit_id"] == out["commit_id"]


def test_commit_default_change_note_names_the_cr(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = open_cr(env, title="口径调整")
    commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}])
    assert f"审核单 #{cr_id}" in _versions(env)[-1]["change_note"]


def test_incremental_rule_and_acceptance_ops(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [{
        "op": "update_block", "id": env["block_id"],
        "rule_ops": [{"op": "upsert", "id": "R-1", "entry": {"name": "销售额口径", "detail": "改成含退款"}}],
        "acceptance_ops": [{"op": "upsert", "entry": {"name": "新增验收", "detail": "新增的验收条件"}}],
    }]))
    b = out["blocks"][0]
    assert (b["version"], b["level"]) == ("2.0.0", "major")  # 规则详述被修改 → MAJOR
    assert b["delta"]["rules_modified"] == ["R-1 销售额口径"]
    assert b["delta"]["acceptance_added"] == ["AC-2 新增验收"]


def test_unknown_item_id_is_409(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"],
                                    "rule_ops": [{"op": "delete", "id": "R-99"}]}])
    assert r.status_code == 409 and "R-99" in r.json()["detail"] and "第 1 条 op" in r.json()["detail"]


def test_api_ops_delta(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    new_api = {**APIS_V1[0], "name": "新接口", "api": "POST /api/daily-report/refresh"}
    out = _ok(commit(env, open_cr(env), [{
        "op": "update_block", "id": env["block_id"],
        "api_ops": [{"op": "upsert", "api": "POST /api/daily-report/refresh", "entry": new_api}]}]))
    assert out["blocks"][0]["level"] == "minor"
    out = _ok(commit(env, open_cr(env), [{
        "op": "update_block", "id": env["block_id"],
        "api_ops": [{"op": "delete", "api": "POST /api/daily-report/refresh"}]}]))
    assert out["blocks"][0]["level"] == "major"  # 任何删除都是 MAJOR


def test_replace_and_ops_on_same_field_is_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"],
                                    "rules": RULES_V1, "rule_ops": []}])
    assert r.status_code == 422 and "不能同时给" in r.json()["detail"]


def test_replacing_a_list_without_ids_never_reuses_old_ids(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"],
                                          "rules": [{"name": "全新规则", "detail": "整体替换后新增"}]}]))
    assert out["blocks"][0]["delta"]["rules_removed"] == ["R-1 销售额口径"]
    assert out["blocks"][0]["delta"]["rules_added"] == ["R-2 全新规则"]  # 不回收 R-1


def test_noop_update_is_422(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"],
                                    "rules": [{"id": "R-1", **RULES_V1[0]}]}])
    assert r.status_code == 422 and "没有产生任何变化" in r.json()["detail"]


def test_title_only_update_does_not_publish_a_version(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"],
                                          "title": "数据采集（改名）"}]))
    assert out["blocks"] == [] and out["capability_versions"] == []
    assert len(_versions(env)) == 1
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).json()["title"] == "数据采集（改名）"


def test_publish_gate_still_applies_and_names_the_block(env):
    """Commit 里新建的模块同样要过结构完备性关口；报错指明是哪个模块、缺哪些项，
    且整个 Commit（包括前面成功的 op）一起回滚。"""
    cr_id = open_cr(env)
    r = commit(env, cr_id, [
        {"op": "update_capability", "id": env["capability_id"], "summary": "ok"},
        _new_block_op(env["capability_id"], "不完备的模块", content_md="太短", rules=[], acceptance=[]),
    ])
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["title"] == "不完备的模块" and len(d["missing"]) == 3  # 背景太短 + 无规则 + 无验收条件
    cap = env["client"].get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["capabilities"][0]
    assert cap["summary"] == "" and cap["blocks"][0]["title"] == "数据采集模块"  # 回滚


# ---------- 原子性 ----------


def test_failed_op_rolls_back_the_whole_commit(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr_id = open_cr(env)
    r = commit(env, cr_id, [
        {"op": "create_business", "ref": "b", "name": "不该出现的大业务"},
        {"op": "update_block", "id": env["block_id"], "content_md": BG},
        {"op": "update_block", "id": env["block_id"], "rule_ops": [{"op": "delete", "id": "R-99"}]},
    ])
    assert r.status_code == 409 and "第 3 条 op" in r.json()["detail"]
    assert len(_versions(env)) == 1  # 第 2 条的发布没有落地
    tree = c.get("/api/v1/tree", headers=env["human"]).json()
    assert [b["name"] for b in tree[0]["businesses"]] == ["运营"]  # 第 1 条的建单也回滚了
    cr = c.get(f"{CR}/{cr_id}", headers=env["human"]).json()
    assert cr["commit_count"] == 0 and cr["status"] == "approved"  # 审核单仍可继续提交 Commit
    _ok(commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}]))


# ---------- 新建结构：$ref、跨小业务、一个 Commit 一个小业务版本 ----------


def test_create_whole_chain_with_refs(env):
    c = env["client"]
    out = _ok(commit(env, open_cr(env), [
        {"op": "create_business", "ref": "b", "name": "采购"},
        {"op": "create_capability", "ref": "c", "business": "$b", "title": "采购下单", "summary": "下采购单"},
        _new_block_op("$c", "下单模块", ref="k"),
    ], covers=["AC-1"]))
    assert set(out["created"]) == {"$b", "$c", "$k"}
    assert out["created"]["$b"]["type"] == "business"
    block = out["blocks"][0]
    assert (block["version"], block["level"], block["created"]) == ("1.0.0", "initial", True)
    assert out["capability_versions"][0]["version"] == "1.0.0"
    idx = c.get("/api/v1/index", headers=env["agent"]).json()
    assert [(b["business"], b["capabilities"][0]["title"], b["capabilities"][0]["summary"])
            for b in idx if b["business"] == "采购"] == [("采购", "采购下单", "下采购单")]
    # 新建的规则 / 验收条件有稳定 id
    got = c.get(f"/api/v1/blocks/{block['block_id']}", headers=env["agent"]).json()
    assert got["rules"][0]["id"] == "R-1" and got["acceptance"][0]["id"] == "AC-1"


def test_bad_refs_are_422(env):
    cr_id = open_cr(env)
    r = commit(env, cr_id, [_new_block_op("$nope")])
    assert r.status_code == 422 and "$nope" in r.json()["detail"]
    r = commit(env, cr_id, [{"op": "create_business", "ref": "x", "name": "a"},
                            {"op": "create_business", "ref": "x", "name": "b"}])
    assert r.status_code == 422 and "重复" in r.json()["detail"]
    r = commit(env, cr_id, [{"op": "create_business", "ref": "9bad", "name": "a"}])
    assert r.status_code == 422


def test_one_capability_version_per_commit_even_with_many_blocks(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [
        _new_block_op(env["capability_id"], "模块甲"),
        _new_block_op(env["capability_id"], "模块乙"),
        {"op": "update_block", "id": env["block_id"], "content_md": BG},
    ]))
    assert len(out["blocks"]) == 3
    assert out["capability_versions"] == [
        {"capability_id": env["capability_id"], "version": "1.1.0", "level": "minor"}]
    caps = c.get(f"/api/v1/capabilities/{env['capability_id']}/versions", headers=env["human"]).json()
    assert [v["version"] for v in caps] == ["1.0.0", "1.1.0"]
    assert len(caps[-1]["manifest"]) == 3  # manifest 含三个模块的当前版本


def test_commit_spanning_two_capabilities(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [
        {"op": "create_capability", "ref": "c2", "business": env["business_id"], "title": "第二个小业务"},
        _new_block_op("$c2", "第二模块"),
        {"op": "update_block", "id": env["block_id"], "content_md": BG},
    ]))
    by_cap = {cv["capability_id"]: cv for cv in out["capability_versions"]}
    assert len(by_cap) == 2
    assert by_cap[env["capability_id"]]["version"] == "1.0.1"
    assert by_cap[out["created"]["$c2"]["id"]]["version"] == "1.0.0"


def test_update_capability_and_business_metadata(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [
        {"op": "update_capability", "id": env["capability_id"], "title": "经营日报 2", "summary": "一句话"},
        {"op": "update_business", "id": env["business_id"], "name": "运营中心"},
    ]))
    assert out["blocks"] == [] and out["capability_versions"] == []
    cap = c.get(f"/api/v1/capabilities/{env['capability_id']}", headers=env["agent"]).json()
    assert (cap["title"], cap["summary"]) == ("经营日报 2", "一句话")
    assert c.get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["name"] == "运营中心"
    r = commit(env, open_cr(env), [{"op": "update_capability", "id": env["capability_id"]}])
    assert r.status_code == 422


# ---------- 归档 / 恢复 ----------


def test_archive_and_restore_via_commit(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    out = _ok(commit(env, open_cr(env), [{"op": "archive_block", "id": env["block_id"]}]))
    assert out["archived_blocks"] == [env["block_id"]]
    assert out["capability_versions"][0] == {
        "capability_id": env["capability_id"], "version": "1.1.0", "level": "minor"}
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).status_code == 404
    assert [a["id"] for a in c.get("/api/v1/archive", headers=env["human"]).json()] == [env["block_id"]]
    # 已归档的模块不能改，也不能重复归档
    r = commit(env, open_cr(env), [{"op": "update_block", "id": env["block_id"], "content_md": BG}])
    assert r.status_code == 409 and "restore_block" in r.json()["detail"]
    assert commit(env, open_cr(env), [{"op": "archive_block", "id": env["block_id"]}]).status_code == 409

    out = _ok(commit(env, open_cr(env), [{"op": "restore_block", "id": env["block_id"]}]))
    assert out["restored_blocks"] == [env["block_id"]]
    assert out["capability_versions"][0]["version"] == "1.2.0"
    assert c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"]).status_code == 200


def test_cannot_archive_and_update_same_block_in_one_commit(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    r = commit(env, open_cr(env), [
        {"op": "update_block", "id": env["block_id"], "content_md": BG},
        {"op": "archive_block", "id": env["block_id"]},
    ])
    assert r.status_code == 409


# ---------- 覆盖检查与完成 ----------


def test_complete_requires_every_acceptance_covered(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr_id = open_cr(env, acceptance=[{"name": "甲", "detail": "验收甲的详述"},
                                     {"name": "乙", "detail": "验收乙的详述"}])
    done = lambda: c.post(f"{CR}/{cr_id}/complete", headers=req_key(env))  # noqa: E731
    assert done().status_code == 409  # 还没有任何 Commit

    _ok(commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}],
               covers=["AC-1"]))
    r = done()
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["AC-2"]
    assert c.get(f"{CR}/{cr_id}", headers=env["human"]).json()["coverage"]["missing"] == ["AC-2"]

    _ok(commit(env, cr_id, [{"op": "update_block", "id": env["block_id"],
                             "content_md": BG + " 再补一句。"}], covers=["AC-2"]))
    r = done()
    assert r.status_code == 200 and r.json()["status"] == "applied" and r.json()["applied_at"]
    # 已完成的审核单不能再提交 Commit，也不能重复完成
    assert commit(env, cr_id, [{"op": "archive_block", "id": env["block_id"]}]).status_code == 409
    assert done().status_code == 409


def test_covers_must_exist_in_the_cr(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = open_cr(env)
    r = commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}],
               covers=["AC-1", "AC-9"])
    assert r.status_code == 422 and "AC-9" in r.json()["detail"]
    assert env["client"].get(f"{CR}/{cr_id}", headers=env["human"]).json()["commit_count"] == 0


def test_commit_without_covers_is_allowed_but_blocks_completion(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    cr_id = open_cr(env)
    _ok(commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}]))
    r = env["client"].post(f"{CR}/{cr_id}/complete", headers=req_key(env))
    assert r.status_code == 409 and r.json()["detail"]["missing"] == ["AC-1"]


# ---------- 预览 ----------


def test_dry_run_previews_without_persisting(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr_id = open_cr(env)
    ops = [{"op": "update_block", "id": env["block_id"], "rule_ops": [
        {"op": "upsert", "entry": {"name": "新规则", "detail": "预览用的新增规则"}}]}]
    out = _ok(commit(env, cr_id, ops, dry_run=True))
    assert out["dry_run"] is True and "commit_id" not in out
    assert (out["blocks"][0]["version"], out["blocks"][0]["level"]) == ("1.1.0", "minor")
    assert len(_versions(env)) == 1  # 不落库
    assert c.get(f"{CR}/{cr_id}", headers=env["human"]).json()["commit_count"] == 0
    # 预览不写审计
    assert not [a for a in c.get("/api/v1/activity", params={"limit": 200}, headers=env["human"]).json()
                if a["action"] == "commit"]
    real = _ok(commit(env, cr_id, ops))
    assert real["blocks"][0]["version"] == "1.1.0" and real["dry_run"] is False


# ---------- 校验与隔离 ----------


def test_ops_shape_validation(env):
    cr_id = open_cr(env)
    publish_v1(env["client"], env["human"], env["block_id"])
    assert commit(env, cr_id, []).status_code == 422
    assert commit(env, cr_id, [{"op": "drop_table"}]).status_code == 422
    r = commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "rule_op": []}])
    assert r.status_code == 422 and "rule_op" in r.json()["detail"]  # 拼错的字段不会被悄悄忽略
    r = commit(env, cr_id, [{"op": "update_block", "id": "x"}])
    assert r.status_code == 422
    r = commit(env, cr_id, [{"op": "update_block", "id": 99999, "content_md": BG}])
    assert r.status_code == 404


def test_ids_from_another_project_are_404(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    other = c.post("/api/v1/projects", json={"name": "别的项目"}, headers=env["human"]).json()["id"]
    glob = make_key(env, "requirements-agent", project_bound=False)
    boss = make_key(env, "reviewer", project_bound=False)  # 人类 key 绑定在本项目，批别的项目要全局审核人

    def other_cr():
        cr_id = c.post(CR, json=cr_body(project_id=other), headers=glob).json()["id"]
        c.post(f"{CR}/{cr_id}/submit", headers=glob)
        approve_cr(env, cr_id, headers=boss)
        return cr_id

    made = c.post(f"{CR}/{other_cr()}/commits", headers=glob, json={"ops": [
        {"op": "create_business", "ref": "b", "name": "别家业务"},
        {"op": "create_capability", "ref": "c", "business": "$b", "title": "别家小业务"},
        _new_block_op("$c", "别家模块", ref="k")]}).json()
    foreign_block = made["created"]["$k"]["id"]
    foreign_business = made["created"]["$b"]["id"]

    # 本项目的审核单碰不到别的项目的对象（404，不泄露存在）；反过来也一样
    mine = open_cr(env)
    for op in ({"op": "update_block", "id": foreign_block, "content_md": BG},
               {"op": "archive_block", "id": foreign_block},
               {"op": "create_capability", "business": foreign_business, "title": "x"}):
        assert commit(env, mine, [op]).status_code == 404, op
    r = c.post(f"{CR}/{other_cr()}/commits", headers=glob, json={"ops": [
        {"op": "update_block", "id": env["block_id"], "content_md": BG}]})
    assert r.status_code == 404
    # 项目绑定的 key 只能在自己项目的审核单上写
    assert c.post(f"{CR}/{other_cr()}/commits", headers=req_key(env), json={"ops": [
        {"op": "archive_block", "id": foreign_block}]}).status_code == 404


def test_commit_is_audited(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr_id = open_cr(env)
    out = _ok(commit(env, cr_id, [{"op": "update_block", "id": env["block_id"], "content_md": BG}],
                     covers=["AC-1"]))
    rows = [a for a in c.get("/api/v1/activity", params={"limit": 200}, headers=env["human"]).json()
            if a["action"] == "commit"]
    assert rows[0]["target"] == f"cr:{cr_id}/commit:{out['commit_id']}"
    assert rows[0]["detail"]["covers"] == ["AC-1"]
