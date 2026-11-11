"""响应声明没有改变线上的 JSON：几个有多种形状的接口，两种形状都能原样出来。"""

from __future__ import annotations

from tests.conftest import change_block, commit, open_cr, publish_v1


def test_diff_has_two_shapes_a_hint_with_one_version_and_the_full_diff_with_two(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    one = c.get(f"/api/v1/blocks/{env['block_id']}/diff", headers=env["human"]).json()
    assert set(one) == {"block_id", "message", "versions"} and one["versions"] == ["1.0.0"]
    change_block(env, env["block_id"], rules=[{"name": "销售额口径", "detail": "改成含退款"}])
    two = c.get(f"/api/v1/blocks/{env['block_id']}/diff", headers=env["human"]).json()
    assert set(two) == {"block_id", "from", "to", "content_diff", "openapi_diff", "delta", "level"}
    assert two["from"] == "1.0.0" and two["level"] == "major" and "rules_modified" in two["delta"]


def test_commit_dry_run_and_real_commit_have_their_own_shapes(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    cr = open_cr(env)
    ops = [{"op": "update_capability", "id": env["capability_id"], "summary": "新摘要"}]
    dry = commit(env, cr, ops, covers=["AC-1"], dry_run=True).json()
    assert dry["dry_run"] is True and "commit_id" not in dry and "seq" not in dry
    real = commit(env, cr, ops, covers=["AC-1"]).json()
    assert real["dry_run"] is False and real["commit_id"] and real["seq"] == 1 and real["covers"] == ["AC-1"]
    assert set(real) - set(dry) == {"commit_id", "seq", "covers"}


def test_create_key_shape_depends_on_whether_the_plaintext_is_returned(env):
    c = env["client"]
    human = c.post("/api/v1/keys", json={"role": "reviewer", "label": "审核人", "project_id": env["project_id"]}, headers=env["human"]).json()
    assert human["key"].startswith("human-") and "mcp_config" not in human  # 没有 .speclock/：明文返回、没有 mcp_config
    assert {"id", "hint", "prefix", "role", "label", "key_file", "project_id", "created_at", "notice"} <= set(human)


def test_error_in_a_work_record_keeps_dict_details(env):
    c = env["client"]
    r = c.get("/api/v1/work/9999", headers=env["agent"])
    assert r.status_code == 404 and r.json() == {"detail": "work 9999 not found", "code": "not_found"}
