"""审计日志的筛选与翻页：动作（精确 / 前缀 / 排除）、谁、对象前缀、时间范围、游标。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from speclock_core import key_hint
from tests.conftest import open_cr, publish_v1, req_key


def _scenario(env):
    """产生一批不同类型的审计：发布、读取、审核单流转、Commit。"""
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    c.get("/api/v1/index", headers=env["agent"])
    c.get(f"/api/v1/blocks/{env['block_id']}", headers=env["agent"])
    cr = open_cr(env)
    c.post(f"/api/v1/change-requests/{cr}/commits", headers=req_key(env),
           json={"ops": [{"op": "update_capability", "id": env["capability_id"], "summary": "新摘要"}],
                 "covers": ["AC-1"]})
    return cr


def _get(env, **params):
    r = env["client"].get("/api/v1/activity", params=params, headers=env["human"])
    assert r.status_code == 200, r.text
    return r.json()


def test_exclude_reads(env):
    _scenario(env)
    everything = _get(env, limit=500)
    assert any(x["action"] == "pull" for x in everything)
    quiet = _get(env, limit=500, exclude_action="pull")
    assert quiet and all(x["action"] != "pull" for x in quiet)
    assert len(quiet) < len(everything)


def test_action_exact_prefix_and_lists(env):
    _scenario(env)
    assert {x["action"] for x in _get(env, action="pull")} == {"pull"}
    cr_actions = {x["action"] for x in _get(env, action="cr_*", limit=500)}
    assert cr_actions and all(a.startswith("cr_") for a in cr_actions)
    assert {"cr_create", "cr_submit", "cr_approve"} <= cr_actions
    mixed = {x["action"] for x in _get(env, action="commit,cr_applied", limit=500)}
    assert mixed == {"commit"}  # cr_applied 在这个场景里还没发生
    # 排除优先于包含的范围：cr_* 里去掉 cr_create
    rest = {x["action"] for x in _get(env, action="cr_*", exclude_action="cr_create", limit=500)}
    assert "cr_create" not in rest and "cr_submit" in rest


def test_actor_and_target_filters(env):
    cr = _scenario(env)
    me = key_hint(env["agent"]["X-API-Key"])
    mine = _get(env, actor=me, limit=500)
    assert mine and all(x["actor"] == me for x in mine)
    for x in _get(env, target_prefix=f"cr:{cr}", limit=500):
        assert x["target"].startswith(f"cr:{cr}")
    assert _get(env, target_prefix=f"cr:{cr}")  # 审核单自己的流转 + 它的 Commit
    blocks = _get(env, target_prefix=f"block:{env['block_id']}", limit=500)
    assert blocks and all(x["target"].startswith(f"block:{env['block_id']}") for x in blocks)
    assert _get(env, target_prefix="nothing:") == []


def test_cursor_paging_covers_everything_without_overlap(env):
    _scenario(env)
    everything = _get(env, limit=500)
    ids = [x["id"] for x in everything]
    assert ids == sorted(ids, reverse=True)
    seen: list[int] = []
    cursor = None
    while True:
        page = _get(env, limit=4, **({"before_id": cursor} if cursor else {}))
        if not page:
            break
        seen.extend(x["id"] for x in page)
        cursor = page[-1]["id"]
    assert seen == ids  # 不重复、不遗漏、顺序一致


def test_time_range(env):
    _scenario(env)
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    assert _get(env, since=future) == []
    assert _get(env, until=past) == []
    assert _get(env, since=past, until=future, limit=500)
    # 带 Z 与不带时区的写法都接受
    assert _get(env, since=past.replace("+00:00", "Z"), limit=1)
    assert _get(env, since=(now - timedelta(days=1)).replace(tzinfo=None).isoformat(), limit=1)


def test_bad_parameters_are_422(env):
    c, h = env["client"], env["human"]
    assert c.get("/api/v1/activity", params={"since": "昨天"}, headers=h).status_code == 422
    assert c.get("/api/v1/activity", params={"until": "x"}, headers=h).status_code == 422
    assert c.get("/api/v1/activity", params={"action": ","}, headers=h).status_code == 422


def test_filters_still_need_audit_read(env):
    c = env["client"]
    assert c.get("/api/v1/activity", params={"action": "pull"}, headers=env["agent"]).status_code == 403
    assert c.get("/api/v1/activity", params={"action": "pull"}).status_code == 401


# ---------- /keys 的活动统计（Agent 视图用） ----------


def test_keys_list_carries_activity_stats(env):
    c, h = env["client"], env["human"]
    publish_v1(c, h, env["block_id"])
    c.get("/api/v1/index", headers=env["agent"])  # 读取
    work = c.get("/api/v1/work", headers=env["agent"]).json()[0]["id"]
    c.post(f"/api/v1/work/{work}/claim", headers=env["agent"])  # 一个动作
    qa = c.post("/api/v1/keys", json={"role": "tester-agent", "label": "没用过的", "project_id": env["project_id"]}, headers=h).json()

    rows = {k["hint"]: k for k in c.get("/api/v1/keys", headers=h).json()}
    agent = rows[key_hint(env["agent"]["X-API-Key"])]
    assert agent["actions_7d"] >= 1 and agent["reads_7d"] >= 1 and agent["last_active_at"]
    unused = rows[qa["hint"]]
    assert (unused["actions_7d"], unused["reads_7d"], unused["last_active_at"]) == (0, 0, None)
    assert all("key" not in k and "hash" not in k for k in rows.values())  # 绝不含明文 / 哈希


def test_after_id_returns_only_newer_events_in_the_same_order(env):
    _scenario(env)
    rows = _get(env, limit=500)
    ids = [x["id"] for x in rows]
    assert ids == sorted(ids, reverse=True)  # 排序仍是新的在前
    mid = ids[len(ids) // 2]
    newer = _get(env, limit=500, after_id=mid)
    assert [x["id"] for x in newer] == [i for i in ids if i > mid]
    assert _get(env, limit=500, after_id=ids[0]) == []  # 已经是最新：什么都没有
    assert len(_get(env, limit=500, after_id=0)) == len(ids)


def test_after_id_combines_with_before_id_and_other_filters(env):
    _scenario(env)
    ids = [x["id"] for x in _get(env, limit=500)]
    low, high = ids[-3], ids[2]
    window = _get(env, limit=500, after_id=low, before_id=high)
    assert [x["id"] for x in window] == [i for i in ids if low < i < high]
    # 事件比 limit 多时拿到的是最新的 limit 条，缺的一段用 before_id 往回补
    latest = _get(env, limit=2, after_id=low)
    assert [x["id"] for x in latest] == ids[:2]
    gap = _get(env, limit=500, after_id=low, before_id=latest[-1]["id"])
    assert [x["id"] for x in latest + gap] == [i for i in ids if i > low]
    assert all(x["action"] != "pull" for x in _get(env, limit=500, after_id=low, exclude_action="pull"))
