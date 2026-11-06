"""小业务（Capability）的可选一句话简述 summary：创建 / 更新（经由 Commit）/ 随索引与读取下发。"""

from __future__ import annotations

from tests.conftest import commit, open_cr, publish_v1


def _ok(env, ops):
    r = commit(env, open_cr(env), ops)
    assert r.status_code == 200, r.text
    return r.json()


def test_summary_defaults_to_empty_and_is_set_via_update(env):
    c = env["client"]
    out = _ok(env, [{"op": "create_capability", "ref": "c", "business": env["business_id"],
                     "title": "售罄率报表"}])
    cid = out["created"]["$c"]["id"]
    caps = c.get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["capabilities"]
    assert next(x for x in caps if x["id"] == cid)["summary"] == ""

    _ok(env, [{"op": "update_capability", "id": cid, "summary": "按门店统计售罄率"}])
    caps = c.get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["capabilities"]
    got = next(x for x in caps if x["id"] == cid)
    assert (got["title"], got["summary"]) == ("售罄率报表", "按门店统计售罄率")


def test_create_with_summary(env):
    out = _ok(env, [{"op": "create_capability", "ref": "c", "business": env["business_id"],
                     "title": "采购", "summary": "采购下单与入库"}])
    cid = out["created"]["$c"]["id"]
    caps = env["client"].get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["capabilities"]
    assert next(x for x in caps if x["id"] == cid)["summary"] == "采购下单与入库"


def test_update_needs_title_or_summary(env):
    r = commit(env, open_cr(env), [{"op": "update_capability", "id": env["capability_id"]}])
    assert r.status_code == 422


def test_update_title_keeps_summary(env):
    c, cid = env["client"], env["capability_id"]
    _ok(env, [{"op": "update_capability", "id": cid, "summary": "每日经营概览"}])
    _ok(env, [{"op": "update_capability", "id": cid, "title": "经营日报 v2"}])
    cap = c.get("/api/v1/tree", headers=env["human"]).json()[0]["businesses"][0]["capabilities"][0]
    assert (cap["title"], cap["summary"]) == ("经营日报 v2", "每日经营概览")


def test_summary_is_delivered_to_agents(env):
    c, a, cid = env["client"], env["agent"], env["capability_id"]
    _ok(env, [{"op": "update_capability", "id": cid, "summary": "每日经营概览"}])
    publish_v1(c, env["human"], env["block_id"])

    index = c.get("/api/v1/index", headers=a).json()
    assert index[0]["capabilities"][0]["summary"] == "每日经营概览"

    listing = c.get("/api/v1/capabilities", headers=a).json()
    assert listing[0]["summary"] == "每日经营概览"

    detail = c.get(f"/api/v1/capabilities/{cid}", headers=a).json()
    assert detail["summary"] == "每日经营概览"
