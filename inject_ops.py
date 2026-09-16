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
from speclock.auth import hash_key, key_hint, new_key
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

PROJECT_NAME = "重庆尚诚购·线上零售（运营工作区）"


def clear_all(db) -> None:
    # 注意：api_keys 不清空——密钥由人管理，重跑注入不吊销任何 key
    for model in (
        Ack, Proposal, AuditLog, BlockVersion, DocumentVersion,
        Block, Document, Domain, Project,
    ):
        db.query(model).delete()
    db.flush()


def ensure_keys(db, project_id: int) -> tuple[str, str]:
    """无 key 时生成一对随机 key（明文仅此一次打印）；已有则原样保留。"""
    existing = db.query(ApiKey).all()
    if existing:
        hints = ", ".join(f"{k.prefix}:{k.hint}" for k in existing)
        print(f"保留现有密钥（明文不可见）：{hints}")
        return "", ""
    human_plain, agent_plain = new_key("human"), new_key("agent")
    db.add(ApiKey(key=hash_key(human_plain), hint=key_hint(human_plain),
                  prefix="human", project_id=project_id, label="inject human"))
    db.add(ApiKey(key=hash_key(agent_plain), hint=key_hint(agent_plain),
                  prefix="agent", project_id=project_id, label="inject agent"))
    db.flush()
    return human_plain, agent_plain


def main() -> None:
    get_engine()
    init_db()
    db = SessionLocal()

    clear_all(db)

    project = Project(name=PROJECT_NAME)
    db.add(project)
    db.flush()

    human_plain, agent_plain = ensure_keys(db, project.id)

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
            result = publish_block(db, block, actor="inject_ops", change_note="初始发布",
                                   fast_track=True, confirm=False)
            created.append((domain_name, document.title, block.title, result.version,
                            result.document_version, len(mod.get("apis", []))))

    db.commit()

    print(f"项目「{PROJECT_NAME}」注入完成，共 {len(domains)} 个大业务、{len(created)} 个模块：")
    for domain_name, doc_title, block_title, ver, doc_ver, api_count in created:
        print(f"  [{domain_name}] {doc_title} / {block_title} @{ver}"
              f"（{api_count} API，文档版本 @{doc_ver}）")
    if human_plain:
        print()
        print("  已生成新密钥（明文仅此一次显示，系统只存哈希，请立即保存）：")
        print(f"  human key (读写/UI): {human_plain}")
        print(f"  agent key (只读+提案): {agent_plain}")
    db.close()


if __name__ == "__main__":
    main()
