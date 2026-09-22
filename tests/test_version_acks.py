"""版本历史接口的回执整合：acks 明细 + ack_state 三态（acked/pending/superseded）。"""

from __future__ import annotations

from tests.conftest import APIS_V2_MINOR, publish_v1


def _ack(env, version, task_desc=""):
    r = env["client"].post(
        f"/api/v1/blocks/{env['block_id']}/ack",
        json={"version": version, "task_desc": task_desc},
        headers=env["agent"],
    )
    assert r.status_code == 201, r.text
    return r.json()


def _versions(env):
    r = env["client"].get(
        f"/api/v1/blocks/{env['block_id']}/versions", headers=env["human"]
    )
    assert r.status_code == 200, r.text
    return r.json()


def _publish_next(env, note="v2"):
    c, h, bid = env["client"], env["human"], env["block_id"]
    c.put(f"/api/v1/blocks/{bid}", json={"apis": APIS_V2_MINOR}, headers=h)
    r = c.post(f"/api/v1/blocks/{bid}/publish",
               json={"change_note": note, "fastTrack": True}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_version_ack_state_pending(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    (v,) = _versions(env)
    assert v["version"] == "1.0.0"
    assert v["ack_state"] == "pending"  # 当前已发布版本且无回执：唯一 actionable
    assert v["acks"] == []


def test_version_ack_state_acked(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    _ack(env, "1.0.0", "实现日报主表前端")
    (v,) = _versions(env)
    assert v["ack_state"] == "acked"
    assert len(v["acks"]) == 1
    rec = v["acks"][0]
    assert rec["agent_key"].startswith("agent-")
    assert rec["task_desc"] == "实现日报主表前端"
    assert rec["created_at"]


def test_version_ack_state_superseded(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    _publish_next(env)

    versions = _versions(env)
    assert [v["version"] for v in versions] == ["1.0.0", "1.1.0"]
    assert versions[0]["ack_state"] == "superseded"  # 无回执且已被取代
    assert versions[1]["ack_state"] == "pending"

    # 旧版本有回执 → acked（即使已被取代）；新版本仍 pending
    _ack(env, "1.0.0")
    versions = _versions(env)
    assert versions[0]["ack_state"] == "acked"
    assert versions[1]["ack_state"] == "pending"


def test_version_multiple_acks_all_returned_in_order(env):
    publish_v1(env["client"], env["human"], env["block_id"])
    _ack(env, "1.0.0", "第一次实现")
    _ack(env, "1.0.0", "修复后重新实现")

    (v,) = _versions(env)
    assert v["ack_state"] == "acked"
    assert [a["task_desc"] for a in v["acks"]] == ["第一次实现", "修复后重新实现"]


def test_voided_version_not_in_list(env):
    c, h, bid = env["client"], env["human"], env["block_id"]
    publish_v1(c, h, bid)
    _ack(env, "1.0.0")
    _publish_next(env)

    r = c.post(f"/api/v1/blocks/{bid}/versions/1.0.0/void", headers=h)
    assert r.status_code == 200, r.text

    versions = _versions(env)
    assert [v["version"] for v in versions] == ["1.1.0"]
    assert versions[0]["ack_state"] == "pending"


def test_acks_endpoint_regression(env):
    """GET /acks 原样保留：记录流含模块名/版本/key/任务。"""
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    _ack(env, "1.0.0", "实现日报主表前端")

    r = c.get("/api/v1/acks", headers=h)
    assert r.status_code == 200, r.text
    rec = next(a for a in r.json() if a["block_id"] == env["block_id"])
    assert rec["block_title"] == "数据采集模块"
    assert rec["version"] == "1.0.0"
    assert rec["agent_key"].startswith("agent-")
    assert rec["task_desc"] == "实现日报主表前端"
