"""Shared fixtures: isolated temporary SQLite DB + TestClient + two keys."""

from __future__ import annotations

import os
import tempfile

import pytest

# Must be set before any speclock import creates an engine.
_TMP = tempfile.mkdtemp(prefix="speclock-test-")
os.environ["SPECLOCK_DB_URL"] = f"sqlite:///{_TMP}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from speclock.auth import new_key  # noqa: E402
from speclock.db import SessionLocal, configure, init_db  # noqa: E402
from speclock.main import app  # noqa: E402
from speclock.models import ApiKey, Block, Document, Domain, Project  # noqa: E402

VALID_YAML_V1 = """\
openapi: "3.0.3"
info: {title: demo, version: "1.0.0"}
paths:
  /api/demo:
    get:
      summary: demo
components:
  schemas:
    DemoRow:
      type: object
      required: [id]
      properties:
        id: {type: integer}
        name: {type: string}
"""

VALID_YAML_V2_MINOR = """\
openapi: "3.0.3"
info: {title: demo, version: "1.1.0"}
paths:
  /api/demo:
    get:
      summary: demo
components:
  schemas:
    DemoRow:
      type: object
      required: [id]
      properties:
        id: {type: integer}
        name: {type: string}
        extra_note: {type: string}
"""

VALID_YAML_V2_BREAKING = """\
openapi: "3.0.3"
info: {title: demo, version: "2.0.0"}
paths:
  /api/demo:
    get:
      summary: demo
components:
  schemas:
    DemoRow:
      type: object
      required: [id]
      properties:
        id: {type: string}
        name: {type: string}
"""

INVALID_YAML = "openapi: 2.0\npaths: /not-a-map\n"


@pytest.fixture()
def env():
    """Fresh DB + TestClient + one human key, one agent key, one demo block."""
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
    block = Block(
        document_id=document.id,
        title="日报主表",
        summary="按大区/门店展示昨日核心指标",
        draft_content_md="# 日报主表\n\n按大区/门店展示昨日销售额、订单量、客单价。",
        draft_openapi_yaml=VALID_YAML_V1,
        draft_nfr_md="- P95 ≤ 500ms",
    )
    db.add(block)
    human_key, agent_key = new_key("human"), new_key("agent")
    db.add(ApiKey(key=human_key, prefix="human", project_id=project.id, label="test human"))
    db.add(ApiKey(key=agent_key, prefix="agent", project_id=project.id, label="test agent"))
    db.commit()
    block_id = block.id
    db.close()

    client = TestClient(app)
    return {
        "client": client,
        "human": {"X-API-Key": human_key},
        "agent": {"X-API-Key": agent_key},
        "block_id": block_id,
        "document_id": document.id,
        "domain_id": domain.id,
        "project_id": project.id,
    }


def publish_v1(client, human, block_id, yaml_text=None):
    """Helper: set draft YAML (optional) and fast-track publish."""
    if yaml_text is not None:
        r = client.put(f"/api/v1/blocks/{block_id}", json={"openapi_yaml": yaml_text},
                       headers=human)
        assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/blocks/{block_id}/publish",
        json={"change_note": "v1", "fastTrack": True},
        headers=human,
    )
    assert r.status_code == 200, r.text
    return r.json()
