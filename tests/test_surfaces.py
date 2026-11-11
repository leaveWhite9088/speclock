"""按「端」分别领取、实现、验收：模块声明端（前端 / 后端…），每个端一条执行记录，各走各的流程。"""

from __future__ import annotations

import copy
import json
import os
import sqlite3

import pytest

from tests.conftest import (
    ACCEPTANCE_V1, APIS_V1, RULES_V1, commit, make_key, open_cr, publish_v1, qa_key,
)

BG = "# 多端模块\n\n前端和后端各自实现的业务背景与流程叙述。"
FE, BE = "前端", "后端"
PASS = "pass"


def _ac(*pairs):
    """pairs: (名称, 端们)；端们为空 = 所有端。"""
    return [{"name": n, "detail": f"{n}的详述", **({"surfaces": list(s)} if s else {})} for n, s in pairs]


def _create(env, surfaces=(FE, BE), acceptance=None, expect=200, title="多端模块"):
    acceptance = acceptance if acceptance is not None else _ac(("页面可用", [FE]), ("接口可用", [BE]), ("口径一致", []))
    op = {"op": "create_block", "capability": env["capability_id"], "title": title, "content_md": BG,
          "rules": RULES_V1, "apis": APIS_V1, "acceptance": acceptance}
    if surfaces is not None:
        op["surfaces"] = list(surfaces)
    r = commit(env, open_cr(env), [op], covers=["AC-1"])
    assert r.status_code == expect, r.text
    return r.json()["blocks"][0]["block_id"] if expect == 200 else r


def _key(env, role, surface="", label=""):
    body = {"role": role, "label": label or f"{role}-{surface or 'any'}", "project_id": env["project_id"]}
    if surface:
        body["surface"] = surface
    r = env["client"].post("/api/v1/keys", json=body, headers=env["human"])
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["key"]}


def _works(env, block_id, headers=None):
    rows = env["client"].get(f"/api/v1/work?block_id={block_id}", headers=headers or env["human"]).json()
    return {w["surface"]: w for w in rows}


def _results(ids):
    return {"results": [{"ac_id": i, "result": PASS, "evidence": "ok"} for i in ids]}


def _run(env, work, ids, implementer, verifier):
    c = env["client"]
    assert c.post(f"/api/v1/work/{work}/claim", headers=implementer).status_code == 200
    r = c.post(f"/api/v1/work/{work}/implementation", json=_results(ids), headers=implementer)
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/work/{work}/verification", json=_results(ids), headers=verifier)
    assert r.status_code == 200, r.text
    return r.json()


def test_publishing_creates_one_record_per_surface(env):
    block = _create(env)
    works = _works(env, block)
    assert set(works) == {FE, BE} and all(w["status"] == "pending" for w in works.values())
    detail = env["client"].get(f"/api/v1/work/{works[FE]['id']}", headers=env["human"]).json()
    assert [s["surface"] for s in detail["siblings"]] == [FE, BE]
    spec = detail["spec"]
    assert spec["surfaces"] == [FE, BE] and {w["surface"] for w in spec["works"]} == {FE, BE}


def test_each_surface_goes_through_the_whole_flow_independently(env):
    c = env["client"]
    block = _create(env)
    w = _works(env, block)
    fe, be = _key(env, "executor-agent", FE), _key(env, "executor-agent", BE)
    # 前端领了、做完，不影响后端还能被领取
    assert c.post(f"/api/v1/work/{w[FE]['id']}/claim", headers=fe).status_code == 200
    assert c.post(f"/api/v1/work/{w[BE]['id']}/claim", headers=be).status_code == 200
    # 同一个端不能重复领取
    r = c.post(f"/api/v1/work/{w[FE]['id']}/claim", headers=_key(env, "executor-agent", FE, "另一个前端"))
    assert r.status_code == 409 and r.json()["code"] == "work_already_claimed"
    # 后端阻塞，前端继续做完
    assert c.post(f"/api/v1/work/{w[BE]['id']}/blocked", json={"reason": "口径没说清"}, headers=be).status_code == 200
    r = c.post(f"/api/v1/work/{w[FE]['id']}/implementation", json=_results(["AC-1", "AC-3"]), headers=fe)
    assert r.status_code == 200 and r.json()["status"] == "implemented" and r.json()["surface"] == FE
    now = _works(env, block)
    assert (now[FE]["status"], now[BE]["status"], now[BE]["reason"]) == ("implemented", "blocked", "口径没说清")


def test_an_acceptance_item_can_name_the_surfaces_responsible_for_it(env):
    c = env["client"]
    block = _create(env)  # AC-1 前端、AC-2 后端、AC-3 所有端
    w = _works(env, block)
    fe = _key(env, "executor-agent", FE)
    detail = c.post(f"/api/v1/work/{w[FE]['id']}/claim", headers=fe).json()
    assert [a["id"] for a in detail["required_acceptance"]] == ["AC-1", "AC-3"]  # 后端的 AC-2 不用管
    assert [a["id"] for a in detail["spec"]["acceptance"]] == ["AC-1", "AC-2", "AC-3"]  # 规格里仍是完整的
    assert [a.get("surfaces") for a in detail["spec"]["acceptance"]] == [[FE], [BE], None]
    r = c.post(f"/api/v1/work/{w[FE]['id']}/implementation", json=_results(["AC-1"]), headers=fe)  # 漏了 AC-3
    assert r.status_code == 422 and "AC-3" in json.dumps(r.json(), ensure_ascii=False)
    r = c.post(f"/api/v1/work/{w[FE]['id']}/implementation", json=_results(["AC-1", "AC-2", "AC-3"]), headers=fe)
    assert r.status_code == 422  # AC-2 是后端的
    assert c.post(f"/api/v1/work/{w[FE]['id']}/implementation", json=_results(["AC-1", "AC-3"]), headers=fe).status_code == 200


def test_a_key_limited_to_a_surface_cannot_touch_another(env):
    c = env["client"]
    block = _create(env)
    w = _works(env, block)
    fe = _key(env, "executor-agent", FE)
    r = c.post(f"/api/v1/work/{w[BE]['id']}/claim", headers=fe)
    assert r.status_code == 403 and r.json()["code"] == "work_surface_mismatch"
    assert c.get("/api/v1/me", headers=fe).json()["surface"] == FE
    # 不限定的 key 行为和以前一样：两个端都能领
    free = env["agent"]
    assert c.post(f"/api/v1/work/{w[BE]['id']}/claim", headers=free).status_code == 200
    assert c.post(f"/api/v1/work/{w[FE]['id']}/claim", headers=free).status_code == 200
    assert c.get("/api/v1/me", headers=free).json()["surface"] == ""


def test_the_verifier_must_differ_from_the_implementer_per_record(env):
    c = env["client"]
    block = _create(env)
    w = _works(env, block)
    admin = env["human"]  # 有 exec.write 和 exec.verify
    ids_fe, ids_be = ["AC-1", "AC-3"], ["AC-2", "AC-3"]
    for surface, ids in ((FE, ids_fe), (BE, ids_be)):
        assert c.post(f"/api/v1/work/{w[surface]['id']}/claim", headers=admin).status_code == 200
        assert c.post(f"/api/v1/work/{w[surface]['id']}/implementation", json=_results(ids), headers=admin).status_code == 200
    # 同一把 key 实现了前端，就不能验收前端……
    r = c.post(f"/api/v1/work/{w[FE]['id']}/verification", json=_results(ids_fe), headers=admin)
    assert r.status_code == 403 and r.json()["code"] == "work_verifier_is_implementer"
    # ……换另一把 key 才行；这把 key 也没实现过别的端，所以可以去验收后端
    assert c.post(f"/api/v1/work/{w[BE]['id']}/verification", json=_results(ids_be), headers=qa_key(env)).status_code == 200


def test_a_module_is_verified_only_when_every_surface_is(env):
    c = env["client"]
    block = _create(env)
    w = _works(env, block)
    impl, tester = env["agent"], qa_key(env)

    def index_status():
        row = [b for d in c.get("/api/v1/index", headers=env["human"]).json() for cap in d["capabilities"]
               for b in cap["blocks"] if b["block_id"] == block][0]
        return row["execution_status"], {x["surface"]: x["status"] for x in row["works"]}

    assert index_status()[0] == "pending"
    assert _run(env, w[FE]["id"], ["AC-1", "AC-3"], impl, tester)["status"] == "verified"
    status, per = index_status()
    assert status == "pending" and per == {FE: "verified", BE: "pending"}  # 后端还没动：整体没完成
    tree = c.get("/api/v1/tree", headers=env["human"]).json()
    node = [b for p in tree for biz in p["businesses"] for cap in biz["capabilities"] for b in cap["blocks"] if b["id"] == block][0]
    assert node["execution_status"] == "pending" and {x["surface"] for x in node["works"]} == {FE, BE}
    # 后端失败 → 汇总里先报失败
    c.post(f"/api/v1/work/{w[BE]['id']}/claim", headers=impl)
    c.post(f"/api/v1/work/{w[BE]['id']}/failed", json={"reason": "跑不通"}, headers=impl)
    assert index_status()[0] == "failed"
    assert _run(env, w[BE]["id"], ["AC-2", "AC-3"], impl, tester)["status"] == "verified"
    assert index_status() == ("verified", {FE: "verified", BE: "verified"})
    versions = c.get(f"/api/v1/blocks/{block}/versions", headers=env["human"]).json()
    assert versions[0]["execution_status"] == "verified" and versions[0]["surfaces"] == [FE, BE]
    assert {e["surface"] for e in versions[0]["events"]} == {FE, BE}
    full = c.get(f"/api/v1/blocks/{block}/versions/1.0.0", headers=env["human"]).json()
    assert full["execution_status"] == "verified" and len(full["works"]) == 2


def test_a_new_version_supersedes_the_open_records_of_every_surface(env):
    c = env["client"]
    block = _create(env)
    old = _works(env, block)
    c.post(f"/api/v1/work/{old[FE]['id']}/claim", headers=env["agent"])
    cr = open_cr(env)
    r = commit(env, cr, [{"op": "update_block", "id": block, "content_md": BG + "\n\n补充了一段新的业务说明。"}], covers=["AC-1"])
    assert r.status_code == 200, r.text
    rows = c.get(f"/api/v1/work?block_id={block}&status=superseded", headers=env["human"]).json()
    assert {x["id"] for x in rows} == {old[FE]["id"], old[BE]["id"]}
    now = _works(env, block)
    assert all(now[s]["version"] != old[s]["version"] for s in (FE, BE))
    assert {w["status"] for w in now.values()} == {"pending"} and set(now) == {FE, BE}
    r = c.post(f"/api/v1/work/{old[FE]['id']}/implementation", json=_results(["AC-1", "AC-3"]), headers=env["agent"])
    assert r.status_code == 409 and r.json()["code"] == "work_superseded"
    assert r.json()["detail"]["latest_work_id"] == now[FE]["id"]  # 指向同一个端的最新记录


def test_list_work_filters_by_surface_and_a_limited_key_defaults_to_its_own(env):
    c = env["client"]
    block = _create(env)
    assert {x["surface"] for x in c.get(f"/api/v1/work?block_id={block}&surface={FE}", headers=env["human"]).json()} == {FE}
    assert {x["surface"] for x in c.get(f"/api/v1/work?block_id={block}", headers=env["human"]).json()} == {FE, BE}
    be = _key(env, "executor-agent", BE)
    assert {x["surface"] for x in c.get(f"/api/v1/work?block_id={block}", headers=be).json()} == {BE}  # 缺省只看自己的端
    assert {x["surface"] for x in c.get(f"/api/v1/work?block_id={block}&surface={FE}", headers=be).json()} == {FE}  # 想看别的端要说明


def test_activity_says_which_surface(env):
    c = env["client"]
    block = _create(env)
    w = _works(env, block)
    c.post(f"/api/v1/work/{w[BE]['id']}/claim", headers=env["agent"])
    rows = [a for a in c.get("/api/v1/activity?limit=100", headers=env["human"]).json() if a["action"] == "exec_claim"]
    assert rows and rows[0]["target"] == f"work:{block}@1.0.0#{BE}" and rows[0]["detail"]["surface"] == BE


def test_modules_without_surfaces_behave_exactly_as_before(env):
    c = env["client"]
    publish_v1(c, env["human"], env["block_id"])
    works = _works(env, env["block_id"])
    assert set(works) == {""} and works[""]["surface"] == ""
    w = works[""]["id"]
    detail = c.post(f"/api/v1/work/{w}/claim", headers=env["agent"]).json()
    assert [a["id"] for a in detail["required_acceptance"]] == [a["id"] for a in detail["spec"]["acceptance"]]
    assert detail["spec"]["surfaces"] == [] and [s["surface"] for s in detail["siblings"]] == [""]
    block = detail["spec"]
    assert block["work_id"] == w and block["execution_status"] == "in_progress"
    # 限定了端的 key 碰不了没声明端的模块（它只属于自己的端）
    fe = _key(env, "executor-agent", FE)
    r = c.post(f"/api/v1/work/{w}/release", headers=fe)
    assert r.status_code == 403 and r.json()["code"] == "work_surface_mismatch"


@pytest.mark.parametrize("surfaces, acceptance, why", [
    ([FE, FE], None, "重复"),
    ([FE, ""], None, "非空"),
    ([FE, BE], _ac(("只有前端的条件", [FE])), "没有负责任何验收条件"),
    ([FE], _ac(("接口可用", [BE]), ("页面", [FE])), "指明了端"),
    ([], _ac(("页面", [FE])), "没有声明任何端"),
])
def test_surface_declarations_are_validated(env, surfaces, acceptance, why):
    r = _create(env, surfaces=surfaces, acceptance=acceptance if acceptance is not None else _ac(("通用", [])), expect=422)
    assert why in json.dumps(r.json(), ensure_ascii=False), r.text


def test_changing_the_surfaces_publishes_a_new_version_and_rebuilds_the_records(env):
    c = env["client"]
    block = _create(env, surfaces=(FE, BE))
    r = commit(env, open_cr(env), [{"op": "update_block", "id": block, "surfaces": [FE, BE, "数据"],
                                     "acceptance": _ac(("页面可用", [FE]), ("接口可用", [BE]), ("数据入库", ["数据"]), ("口径一致", []))}],
               covers=["AC-1"])
    assert r.status_code == 200, r.text
    now = _works(env, block)
    assert set(now) == {FE, BE, "数据"}
    same = commit(env, open_cr(env), [{"op": "update_block", "id": block, "surfaces": [FE, BE, "数据"]}], covers=["AC-1"])
    assert same.status_code == 422  # 没有变化


def test_the_acceptance_delta_notices_a_change_of_responsible_surfaces(env):
    c = env["client"]
    block = _create(env)
    r = commit(env, open_cr(env), [{"op": "update_block", "id": block,
                                     "acceptance": [{"id": f"AC-{i}", **a} for i, a in enumerate(
                                         _ac(("页面可用", [FE, BE]), ("接口可用", [BE]), ("口径一致", [])), 1)]}],
               covers=["AC-1"])
    assert r.status_code == 200, r.text
    assert r.json()["blocks"][0]["delta"]["acceptance_modified"] == ["AC-1 页面可用"]


def test_legacy_execution_table_is_rebuilt_without_losing_records(tmp_path):
    """老库的执行记录表唯一约束是 (block_id, version)：升级后按端分开，已有记录都是默认端，事件和 id 原样保留。"""
    from speclock_core import SessionLocal, configure, init_db
    from speclock_core import ExecutionEvent, ExecutionRecord

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE execution_records (id INTEGER NOT NULL PRIMARY KEY, block_id INTEGER NOT NULL, "
                 "version VARCHAR NOT NULL, status VARCHAR NOT NULL DEFAULT 'pending', claimed_by VARCHAR NOT NULL DEFAULT '', "
                 "claimed_by_key_id INTEGER, implemented_by_key_id INTEGER, reason TEXT NOT NULL DEFAULT '', "
                 "results_json TEXT NOT NULL DEFAULT '[]', verification_json TEXT NOT NULL DEFAULT '[]', "
                 "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, CONSTRAINT uq_exec_block_version UNIQUE (block_id, version))")
    conn.execute("CREATE TABLE execution_events (id INTEGER NOT NULL PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES execution_records (id), "
                 "event VARCHAR NOT NULL, from_status VARCHAR NOT NULL DEFAULT '', to_status VARCHAR NOT NULL, actor VARCHAR NOT NULL DEFAULT '', "
                 "note TEXT NOT NULL DEFAULT '', detail_json TEXT NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO execution_records (id, block_id, version, status, claimed_by, created_at, updated_at) "
                 "VALUES (7, 3, '1.0.0', 'implemented', 'agent-…abcd', '2026-01-01', '2026-01-02')")
    conn.execute("INSERT INTO execution_events (record_id, event, to_status, created_at) VALUES (7, 'created', 'pending', '2026-01-01')")
    conn.commit()
    conn.close()
    configure(f"sqlite:///{tmp_path}/old.db")
    try:
        init_db()
        init_db()  # 幂等
        db = SessionLocal()
        rec = db.query(ExecutionRecord).one()
        assert (rec.id, rec.block_id, rec.version, rec.surface, rec.status) == (7, 3, "1.0.0", "", "implemented")
        assert db.query(ExecutionEvent).one().record_id == 7
        db.add(ExecutionRecord(block_id=3, version="1.0.0", surface=FE, status="pending"))  # 现在同一版本可以有第二个端
        db.commit()
        assert db.query(ExecutionRecord).count() == 2
        db.close()
    finally:
        configure(os.environ["SPECLOCK_DB_URL"])
