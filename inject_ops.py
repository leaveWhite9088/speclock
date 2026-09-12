"""清空 demo 数据，注入「重庆尚诚购·线上零售」运营工作区真实业务文档。

数据来源：.inject_data/*.json（由前端仓 chongqing-retail-web 源码提取）
层级映射：Project → Domain(大业务) → Document(小业务) → Block(模块)，
全部模块以 1.0.0 发布，文档版本随之派生。重跑会再次清空，幂等。

Usage:
    .venv/Scripts/python.exe inject_ops.py
"""

from __future__ import annotations

import json
from pathlib import Path

from speclock.api_admin import publish_block
from speclock.db import SessionLocal, get_engine, init_db
from speclock.models import (
    Ack,
    ApiKey,
    AuditLog,
    Block,
    BlockVersion,
    Document,
    DocumentVersion,
    Domain,
    Project,
    Proposal,
)

DATA_DIR = Path(__file__).parent / ".inject_data"

DEFAULT_HUMAN_KEY = "human-dev-0000000000000000000000000001"
DEFAULT_AGENT_KEY = "agent-dev-0000000000000000000000000001"

PROJECT_NAME = "重庆尚诚购·线上零售（运营工作区）"


def clear_all(db) -> None:
    for model in (
        Ack, Proposal, AuditLog, BlockVersion, DocumentVersion,
        Block, Document, Domain, ApiKey, Project,
    ):
        db.query(model).delete()
    db.flush()


def main() -> None:
    get_engine()
    init_db()
    db = SessionLocal()

    clear_all(db)

    project = Project(name=PROJECT_NAME)
    db.add(project)
    db.flush()

    human_key = os_environ_key("SPECLOCK_HUMAN_KEY", DEFAULT_HUMAN_KEY)
    agent_key = os_environ_key("SPECLOCK_AGENT_KEY", DEFAULT_AGENT_KEY)
    db.add(ApiKey(key=human_key, prefix="human", project_id=project.id, label="ops human"))
    db.add(ApiKey(key=agent_key, prefix="agent", project_id=project.id, label="ops agent"))
    db.flush()

    domains: dict[str, Domain] = {}
    created = []
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"未找到数据文件：{DATA_DIR}")

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        domain_name = payload["domain"]
        domain = domains.get(domain_name)
        if domain is None:
            domain = Domain(project_id=project.id, name=domain_name)
            db.add(domain)
            db.flush()
            domains[domain_name] = domain

        document = Document(domain_id=domain.id, title=payload["document"], doc_type="business")
        db.add(document)
        db.flush()

        for mod in payload["modules"]:
            block = Block(
                document_id=document.id,
                title=mod["title"],
                summary=mod.get("summary", ""),
                draft_content_md=mod.get("content_md", ""),
                draft_apis_json=json.dumps(mod.get("apis", []), ensure_ascii=False),
                draft_nfr_md=mod.get("nfr_md", ""),
            )
            db.add(block)
            db.flush()
            result = publish_block(db, block, actor=human_key, change_note="初始发布",
                                   fast_track=True, confirm=False)
            created.append((domain_name, document.title, block.title, result.version,
                            result.document_version, len(mod.get("apis", []))))

    db.commit()

    print(f"项目「{PROJECT_NAME}」注入完成，共 {len(domains)} 个大业务、{len(created)} 个模块：")
    for domain_name, doc_title, block_title, ver, doc_ver, api_count in created:
        print(f"  [{domain_name}] {doc_title} / {block_title} @{ver}"
              f"（{api_count} API，文档版本 @{doc_ver}）")
    print()
    print(f"  human key (读写/UI): {human_key}")
    print(f"  agent key (只读+提案): {agent_key}")
    db.close()


def os_environ_key(env_name: str, default: str) -> str:
    import os
    return os.environ.get(env_name, default)


if __name__ == "__main__":
    main()
