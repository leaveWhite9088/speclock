"""Shared fixtures: isolated temporary SQLite DB + TestClient + two keys."""

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
from speclock.models import ApiKey, Block, Document, Domain, Project  # noqa: E402

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
    """Fresh DB + TestClient + one human key, one agent key, one demo module."""
    configure(os.environ["SPECLOCK_DB_URL"])
    from speclock.db import Base, get_engine

    Base.metadata.drop_all(get_engine())
    init_db()
    db = SessionLocal()

    project = Project(name="测试项目")
    db.add(project)
    db.flush()
    domain = Domain(project_id=project.id, name="运营")
    db.add(domain)
    db.flush()
    document = Document(domain_id=domain.id, title="经营日报", doc_type="business")
    db.add(document)
    db.flush()
    import json

    block = Block(
        document_id=document.id,
        title="数据采集模块",
        summary="汇总前一日经营数据并落库",
        draft_content_md="# 数据采集模块\n\n每日 06:00 汇总前一日经营数据。",
        draft_rules_json=json.dumps(RULES_V1, ensure_ascii=False),
        draft_edge_md="",
        draft_apis_json=json.dumps(APIS_V1, ensure_ascii=False),
        draft_nfr_md="- 采集状态查询 P95 ≤ 300ms",
    )
    db.add(block)
    human_key, agent_key = new_key("human"), new_key("agent")
    db.add(ApiKey(key=hash_key(human_key), hint=key_hint(human_key),
                  prefix="human", project_id=project.id, label="test human"))
    db.add(ApiKey(key=hash_key(agent_key), hint=key_hint(agent_key),
                  prefix="agent", project_id=project.id, label="test agent"))
    db.commit()
    block_id = block.id
    document_id = document.id
    domain_id = domain.id
    project_id = project.id
    db.close()

    client = TestClient(app)
    return {
        "client": client,
        "human": {"X-API-Key": human_key},
        "agent": {"X-API-Key": agent_key},
        "block_id": block_id,
        "document_id": document_id,
        "domain_id": domain_id,
        "project_id": project_id,
    }


def publish_v1(client, human, block_id, apis=None):
    """Helper: set draft APIs (optional) and fast-track publish."""
    if apis is not None:
        r = client.put(f"/api/v1/blocks/{block_id}", json={"apis": apis}, headers=human)
        assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/blocks/{block_id}/publish",
        json={"change_note": "v1", "fastTrack": True},
        headers=human,
    )
    assert r.status_code == 200, r.text
    return r.json()


def create_module(client, human, document_id, title, apis=None):
    """Helper: create a second module (draft) in the same document.

    默认带上合规的背景叙述与规则清单，使后续 publish 能过结构完备性校验。
    """
    body = {
        "document_id": document_id,
        "title": title,
        "summary": title,
        "content_md": f"# {title}\n\n测试用业务背景与流程叙述（超过二十个字符）。",
        "rules": RULES_V1,
    }
    if apis is not None:
        body["apis"] = apis
    r = client.post("/api/v1/blocks", json=body, headers=human)
    assert r.status_code == 201, r.text
    return r.json()["id"]
