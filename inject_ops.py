"""清空 demo 数据，注入「重庆尚诚购·线上零售」运营工作区真实业务文档。

数据来源：.inject_data/*.json（由前端仓 chongqing-retail-web 源码提取）
层级映射：Project → Business(大业务) → Capability(小业务) → Block(模块)，
全部模块以 1.0.0 发布，小业务版本随之派生。重跑会再次清空，幂等。

Usage:
    .venv/Scripts/python.exe inject_ops.py
"""

from __future__ import annotations

import json
from pathlib import Path

from speclock.engine import publish_block
from speclock.auth import hash_key, key_hint, new_key
from speclock.db import SessionLocal, get_engine, init_db
from speclock.models import (
    Ack,
    ApiKey,
    AuditLog,
    Block,
    BlockVersion,
    Capability,
    CapabilityVersion,
    Business,
    ChangeRequest,
    Commit,
    Project,
)

DATA_DIR = Path(__file__).parent / ".inject_data"

PROJECT_NAME = "重庆尚诚购·线上零售（运营工作区）"


def clear_all(db) -> None:
    # 注意：api_keys 不清空——密钥由人管理，重跑注入不吊销任何 key
    for model in (
        Ack, AuditLog, BlockVersion, CapabilityVersion, Commit, ChangeRequest,
        Block, Capability, Business, Project,
    ):
        db.query(model).delete()
    db.flush()


def ensure_keys(db, project_id: int) -> str:
    """无 key 时生成一把 admin key（明文仅此一次打印）；已有则原样保留。"""
    existing = db.query(ApiKey).all()
    if existing:
        hints = ", ".join(f"{k.prefix}:{k.hint}" for k in existing)
        print(f"保留现有密钥（明文不可见）：{hints}")
        return ""
    from speclock.permissions import get_role

    admin_plain = new_key("human")
    admin = get_role(db, "admin")
    db.add(ApiKey(key=hash_key(admin_plain), hint=key_hint(admin_plain), prefix="human",
                  role_id=admin.id, project_id=project_id, label="inject admin"))
    db.flush()
    return admin_plain


def main() -> None:
    get_engine()
    init_db()
    db = SessionLocal()

    clear_all(db)

    project = Project(name=PROJECT_NAME)
    db.add(project)
    db.flush()

    admin_plain = ensure_keys(db, project.id)

    businesses: dict[str, Business] = {}
    created = []
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"未找到数据文件：{DATA_DIR}")

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        business_name = payload["business"]
        business = businesses.get(business_name)
        if business is None:
            business = Business(project_id=project.id, name=business_name)
            db.add(business)
            db.flush()
            businesses[business_name] = business

        capability = Capability(business_id=business.id, title=payload["capability"])
        db.add(capability)
        db.flush()

        for mod in payload["modules"]:
            block = Block(
                capability_id=capability.id,
                title=mod["title"],
                summary=mod.get("summary", ""),
                draft_content_md=mod.get("content_md", ""),
                draft_apis_json=json.dumps(mod.get("apis", []), ensure_ascii=False),
                draft_acceptance_json=json.dumps(
                    mod.get("acceptance", []), ensure_ascii=False
                ),
            )
            db.add(block)
            db.flush()
            result = publish_block(db, block, actor="inject_ops", change_note="初始发布",
                                   enforce_readiness=False)
            created.append((business_name, capability.title, block.title, result.version,
                            result.capability_version, len(mod.get("apis", []))))

    db.commit()

    print(f"项目「{PROJECT_NAME}」注入完成，共 {len(businesses)} 个大业务、{len(created)} 个模块：")
    for business_name, doc_title, block_title, ver, doc_ver, api_count in created:
        print(f"  [{business_name}] {doc_title} / {block_title} @{ver}"
              f"（{api_count} API，小业务版本 @{doc_ver}）")
    if admin_plain:
        print()
        print("  已生成新密钥（明文仅此一次显示，系统只存哈希，请立即保存）：")
        print(f"  admin key (拥有全部权限): {admin_plain}")
    db.close()


if __name__ == "__main__":
    main()
