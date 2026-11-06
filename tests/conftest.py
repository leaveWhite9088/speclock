"""Shared fixtures: isolated temporary SQLite DB + TestClient + keys + CR/Commit helpers."""

from __future__ import annotations

import copy
import os
import tempfile

import pytest

# Must be set before any speclock import creates an engine.
_TMP = tempfile.mkdtemp(prefix="speclock-test-")
os.environ["SPECLOCK_DB_URL"] = f"sqlite:///{_TMP}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from speclock.auth import hash_key, key_hint, new_key  # noqa: E402
from speclock.db import SessionLocal, configure, init_db  # noqa: E402
from speclock.main import app  # noqa: E402
from speclock.engine import publish_block  # noqa: E402
from speclock.models import ApiKey, Block, Capability, Business, Project  # noqa: E402
from speclock.permissions import get_role  # noqa: E402

APIS_V1 = [
    {
        "name": "拉取日报主表",
        "api": "GET /api/daily-report",
        "desc": "前端日报页调用，拉取某日经营主表数据；只读无副作用",
        "request": [
            {"name": "date", "type": "string", "required": True, "description": "查询日期"},
        ],
        "response": [
            {"name": "sales", "type": "number", "required": True, "description": "销售额"},
            {"name": "orders", "type": "integer", "required": True, "description": "订单量"},
        ],
    }
]

RULES_V1 = [
    {"name": "销售额口径", "detail": "支付成功订单金额合计（不含退款）"},
]

ACCEPTANCE_V1 = [
    {"name": "日报数据完整", "detail": "每日 06:30 前日报主表数据采集完成，无缺失门店"},
]

APIS_NO_DESC = copy.deepcopy(APIS_V1)
del APIS_NO_DESC[0]["desc"]

APIS_V2_MINOR = copy.deepcopy(APIS_V1)
APIS_V2_MINOR[0]["response"].append(
    {"name": "extra_note", "type": "string", "required": False, "description": "运营备注"}
)

APIS_V2_BREAKING = copy.deepcopy(APIS_V1)
APIS_V2_BREAKING[0]["response"][0]["type"] = "string"  # sales: number -> string

APIS_FIELD_REMOVED = copy.deepcopy(APIS_V1)
del APIS_FIELD_REMOVED[0]["response"][1]  # remove orders

APIS_INVALID_TYPE = copy.deepcopy(APIS_V1)
APIS_INVALID_TYPE[0]["response"][0]["type"] = "text"

APIS_INVALID_API_NAME = copy.deepcopy(APIS_V1)
APIS_INVALID_API_NAME[0]["api"] = "FETCH daily-report"

APIS_EMPTY_FIELD_NAME = copy.deepcopy(APIS_V1)
APIS_EMPTY_FIELD_NAME[0]["response"][0]["name"] = "  "


@pytest.fixture()
def env():
    """Fresh DB + TestClient + one admin human key, one executor agent key, one demo module
    （模块只有草稿，未发布；用 publish_v1 发布）。需求 Agent / 审核人 key 按需用
    req_key(env) / reviewer_key(env) 创建。"""
    configure(os.environ["SPECLOCK_DB_URL"])
    from speclock.db import Base, get_engine

    Base.metadata.drop_all(get_engine())
    init_db()
    db = SessionLocal()

    project = Project(name="测试项目")
    db.add(project)
    db.flush()
    business = Business(project_id=project.id, name="运营")
    db.add(business)
    db.flush()
    capability = Capability(business_id=business.id, title="经营日报")
    db.add(capability)
    db.flush()
    import json

    block = Block(
        capability_id=capability.id,
        title="数据采集模块",
        summary="汇总前一日经营数据并落库",
        draft_content_md="# 数据采集模块\n\n每日 06:00 汇总前一日经营数据。",
        draft_rules_json=json.dumps(RULES_V1, ensure_ascii=False),
        draft_apis_json=json.dumps(APIS_V1, ensure_ascii=False),
        draft_acceptance_json=json.dumps(ACCEPTANCE_V1, ensure_ascii=False),
    )
    db.add(block)
    human_key, agent_key = new_key("human"), new_key("agent")
    admin, executor = get_role(db, "admin"), get_role(db, "executor-agent")
    db.add(ApiKey(key=hash_key(human_key), hint=key_hint(human_key), prefix="human",
                  role_id=admin.id, project_id=project.id, label="test human"))
    db.add(ApiKey(key=hash_key(agent_key), hint=key_hint(agent_key), prefix="agent",
                  role_id=executor.id, project_id=project.id, label="test agent"))
    db.commit()
    block_id = block.id
    capability_id = capability.id
    business_id = business.id
    project_id = project.id
    db.close()

    client = TestClient(app)
    return {
        "client": client,
        "human": {"X-API-Key": human_key},
        "agent": {"X-API-Key": agent_key},
        "block_id": block_id,
        "capability_id": capability_id,
        "business_id": business_id,
        "project_id": project_id,
    }


def publish_v1(client, human, block_id, apis=None):
    """Helper: 直接用内部发布引擎发布模块草稿（对外没有任何直接发布接口）。
    apis 可选：先改草稿 API 再发布。返回值形如 PublishResult 的 dict。"""
    db = SessionLocal()
    try:
        block = db.get(Block, block_id)
        if apis is not None:
            import json

            block.draft_apis_json = json.dumps(apis, ensure_ascii=False)
        result = publish_block(db, block, actor=key_hint(human["X-API-Key"]), change_note="v1")
        return result.model_dump()
    finally:
        db.close()


def create_module(client, human, capability_id, title, apis=None):
    """Helper: 直接建一个草稿模块（同一小业务下），返回 id。

    默认带上合规的背景叙述与规则清单，使后续 publish_v1 能过结构完备性校验。
    """
    import json

    db = SessionLocal()
    try:
        block = Block(
            capability_id=capability_id,
            title=title,
            summary=title,
            draft_content_md=f"# {title}\n\n测试用业务背景与流程叙述（超过二十个字符）。",
            draft_rules_json=json.dumps(RULES_V1, ensure_ascii=False),
            draft_apis_json=json.dumps(apis or [], ensure_ascii=False),
            draft_acceptance_json=json.dumps(ACCEPTANCE_V1, ensure_ascii=False),
        )
        db.add(block)
        db.commit()
        return block.id
    finally:
        db.close()


# ---------- 审核单 / Commit helpers ----------


def make_key(env, role, project_bound=True, label=""):
    """用 admin 创建一把指定角色的 key，返回请求头。"""
    body = {"role": role, "label": label or role}
    if project_bound:
        body["project_id"] = env["project_id"]
    r = env["client"].post("/api/v1/keys", json=body, headers=env["human"])
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["key"]}


def req_key(env):
    """需求 Agent key（缓存）。"""
    if "_req" not in env:
        env["_req"] = make_key(env, "requirements-agent")
    return env["_req"]


def reviewer_key(env):
    """审核人 key（缓存）。"""
    if "_reviewer" not in env:
        env["_reviewer"] = make_key(env, "reviewer")
    return env["_reviewer"]


DEFAULT_CR_ACCEPTANCE = [{"name": "变更生效", "detail": "变更后的业务行为符合预期，旧行为不再出现"}]


def cr_body(**over):
    body = {
        "title": "调整业务",
        "intent": "业务口径发生了变化，需要同步规格",
        "expected_outcome": "规格反映新的业务口径",
        "acceptance": DEFAULT_CR_ACCEPTANCE,
    }
    body.update(over)
    return body


def open_cr(env, approve=True, **over):
    """需求 Agent 建单 → 提交 →（可选）人批准。返回审核单 id。"""
    c = env["client"]
    r = c.post("/api/v1/change-requests", json=cr_body(**over), headers=req_key(env))
    assert r.status_code == 201, r.text
    cr_id = r.json()["id"]
    r = c.post(f"/api/v1/change-requests/{cr_id}/submit", headers=req_key(env))
    assert r.status_code == 200, r.text
    if approve:
        approve_cr(env, cr_id)
    return cr_id


def approve_cr(env, cr_id, headers=None, **over):
    c = env["client"]
    headers = headers or env["human"]
    cr = c.get(f"/api/v1/change-requests/{cr_id}", headers=headers).json()
    body = {"content_hash": cr["content_hash"], "via": "button"}
    body.update(over)
    r = c.post(f"/api/v1/change-requests/{cr_id}/approve", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def commit(env, cr_id, ops, covers=None, change_note="", dry_run=False):
    """需求 Agent 在审核单下提交 Commit，返回原始 Response。"""
    return env["client"].post(
        f"/api/v1/change-requests/{cr_id}/commits",
        json={"ops": ops, "covers": covers or [], "change_note": change_note,
              "dryRun": dry_run},
        headers=req_key(env),
    )


def change_block(env, block_id, expect=200, note="x", **fields):
    """新开一个已批准审核单，提交 update_block Commit（fields 是 update_block 的字段，
    如 apis= / rules= / acceptance= / content_md= / rule_ops=）。expect=200 时返回
    扁平化结果 {version, level, delta, capability_version, raw}；否则返回 Response。"""
    cr_id = open_cr(env)
    r = commit(env, cr_id, [{"op": "update_block", "id": block_id, **fields}],
               covers=["AC-1"], change_note=note)
    if expect != 200:
        return r
    assert r.status_code == 200, r.text
    out = r.json()
    b = out["blocks"][0]
    cap = next(cv for cv in out["capability_versions"] if cv["capability_id"] == b["capability_id"])
    return {"version": b["version"], "level": b["level"], "delta": b["delta"],
            "capability_version": cap["version"], "raw": out}
