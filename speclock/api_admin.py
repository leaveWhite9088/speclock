"""Admin (write) API — every endpoint here requires a ``human-*`` key.

Agent keys are rejected with 403 by the ``require_human`` dependency; this
router is the physical write boundary of the system. In production this
router would be deployed as a separate service with separate credentials.

发布语义：发布动作只针对单个模块（分模块发布）；每次模块发布成功时，
所属文档自动派生一个新的 DocumentVersion（manifest 快照）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from speclock import diffing
from speclock.auth import audit, hash_key, key_hint, new_key, require_human
from speclock.db import get_db
from speclock.models import (
    Ack,
    ApiKey,
    Block,
    BlockVersion,
    Document,
    DocumentVersion,
    Domain,
    Project,
    Proposal,
    utcnow,
)
from speclock.schemas import (
    BlockCreate,
    BlockUpdate,
    DocumentCreate,
    DomainCreate,
    KeyCreate,
    ProjectCreate,
    PublishRequest,
    PublishResult,
    RenameRequest,
    ResolveRequest,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["admin"],
    dependencies=[Depends(require_human)],
)


def _get_block(db: Session, block_id: int) -> Block:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    return block


def _published_version(db: Session, block: Block, version: str) -> BlockVersion:
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == version)
        .first()
    )
    if bv is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {version}")
    return bv


def _validate_apis_or_422(apis: list[dict]) -> list[dict]:
    try:
        return diffing.validate_apis(apis)
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"API 列表不合法: {exc}") from exc


def _validate_rules_or_422(rules: list[dict]) -> list[dict]:
    try:
        return diffing.validate_rules(rules)
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"业务规则清单不合法: {exc}") from exc


CONTENT_MD_MIN_LEN = 20  # 业务背景与流程叙述的最短长度（去空白后）


def _check_publish_readiness(block: Block) -> list[str]:
    """发布关口「结构完备性」校验：返回全部缺失项（中文），空列表 = 可发布。

    - 业务背景与流程叙述（draft_content_md）非空且至少 20 个字符；
    - 业务规则清单至少 1 条且每条 name/detail 非空；
    - 每条 API 的 desc（端点语义）非空。
    """
    problems: list[str] = []
    if len((block.draft_content_md or "").strip()) < CONTENT_MD_MIN_LEN:
        problems.append(
            f"业务背景与流程叙述不能为空，且至少 {CONTENT_MD_MIN_LEN} 个字符"
            f"（当前 {len((block.draft_content_md or '').strip())} 个）"
        )
    try:
        rules = diffing.validate_rules(json.loads(block.draft_rules_json or "[]"))
    except diffing.ApisValidationError as exc:
        problems.append(f"业务规则清单不合法：{exc}")
        rules = []
    if not rules:
        problems.append("业务规则清单至少需要 1 条规则（每条含规则名与详述）")
    try:
        apis = diffing.validate_apis(
            json.loads(block.draft_apis_json or "[]"), require_desc=False
        )
    except diffing.ApisValidationError as exc:
        problems.append(f"API 列表不合法：{exc}")
    else:
        for i, entry in enumerate(apis):
            if not entry["desc"]:
                problems.append(f"第 {i + 1} 个 API（{entry['name']}）缺少端点语义描述 desc")
    return problems


def _derive_document_version(
    db: Session, block: Block, module_level: str, actor: str, change_note: str
) -> str:
    """模块发布成功后派生文档版本：manifest = 该文档全部已发布模块的版本清单。"""
    doc = db.get(Document, block.document_id)
    doc_version = diffing.derive_document_version(doc.current_version, module_level)
    blocks = db.query(Block).filter(Block.document_id == doc.id).all()
    manifest = {
        str(b.id): {"title": b.title, "version": b.current_published_version}
        for b in blocks
        if b.status == "published" and b.current_published_version is not None
    }
    db.add(
        DocumentVersion(
            document_id=doc.id,
            version=doc_version,
            manifest_json=json.dumps(manifest, ensure_ascii=False),
            triggered_by_block_id=block.id,
            change_note=change_note,
            published_by=actor,
        )
    )
    doc.current_version = doc_version
    audit(
        db,
        actor,
        "publish",
        f"document:{doc.id}@{doc_version}",
        {"triggered_by_block": block.id, "manifest": manifest},
    )
    return doc_version


def publish_block(
    db: Session,
    block: Block,
    actor: str,
    change_note: str,
    fast_track: bool,
    confirm: bool,
    dry_run: bool = False,
) -> PublishResult:
    """Snapshot the working draft into a new immutable BlockVersion, then
    derive a new DocumentVersion for the owning document.

    两通道语义（方案 B）：
    - dry_run=True：只返回预览（将发布的版本号 / delta / 破坏性 / 预测文档
      版本），不落库、不写审计；
    - fastTrack（秒批）：仅允许非破坏性 diff，破坏性直接 409 并引导取消秒批；
    - 破坏性变更的真实发布必须 confirm=true（来自确认视图的知晓勾选）。

    发布关口先做「结构完备性」校验（背景叙述 / 规则清单 / API desc），
    不满足返回 422 并列出全部缺失项；dryRun 预览同样受校验约束。
    """
    problems = _check_publish_readiness(block)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={"error": "模块结构不完备，不能发布", "missing": problems},
        )
    apis = _validate_apis_or_422(json.loads(block.draft_apis_json or "[]"))
    rules = _validate_rules_or_422(json.loads(block.draft_rules_json or "[]"))

    old_apis: list = []
    old_rules: list = []
    if block.current_published_version is not None:
        old_bv = _published_version(db, block, block.current_published_version)
        old_apis = json.loads(old_bv.apis_json or "[]")
        old_rules = json.loads(old_bv.rules_json or "[]")
    d = diffing.delta(old_apis, apis)
    d.update(diffing.rules_delta(old_rules, rules))  # rules 变化不算破坏性
    breaking = diffing.is_breaking(d)
    affected = d["removed"] + d["modified"]
    groups = diffing.group_delta(d, old_apis, apis)
    version, level = diffing.next_module_version(block.current_published_version, d)

    if dry_run:
        doc = db.get(Document, block.document_id)
        return PublishResult(
            block_id=block.id,
            version=version,
            document_id=block.document_id,
            document_version=diffing.derive_document_version(doc.current_version, level),
            delta=d,
            breaking=breaking,
            affected=affected,
            groups=groups,
        )

    if breaking and fast_track:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "包含破坏性变更，请取消秒批以查看影响清单并确认",
                "breaking": True,
                "affected": affected,
            },
        )
    if breaking and not confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "breaking changes require confirm=true",
                "breaking": True,
                "affected": affected,
            },
        )

    bv = BlockVersion(
        block_id=block.id,
        version=version,
        content_md=block.draft_content_md,
        rules_json=json.dumps(rules, ensure_ascii=False),
        apis_json=json.dumps(apis, ensure_ascii=False),
        openapi_yaml=diffing.apis_to_openapi_yaml(apis),
        nfr_md=block.draft_nfr_md,
        change_note=change_note,
        delta_json=json.dumps(d, ensure_ascii=False),
        published_by=actor,
    )
    db.add(bv)
    block.current_published_version = version
    block.status = "published"
    # 发布新版本 → 完成标记自动重置（新版本内容的实现必然滞后）；
    # completed_version 保留为「上次完成的版本号」供参考
    block.completed = False
    block.completed_at = None
    audit(
        db,
        actor,
        "publish",
        f"block:{block.id}@{version}",
        {"change_note": change_note, "fastTrack": fast_track, "breaking": breaking, "delta": d},
    )
    doc_version = _derive_document_version(db, block, level, actor, change_note)
    db.commit()
    return PublishResult(
        block_id=block.id,
        version=version,
        document_id=block.document_id,
        document_version=doc_version,
        delta=d,
        breaking=breaking,
        affected=affected,
        groups=groups,
    )


# ---------- taxonomy CRUD ----------


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name} for p in db.query(Project).order_by(Project.id).all()]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=body.name)
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name}


@router.put("/projects/{project_id}")
def rename_project(project_id: int, body: RenameRequest, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
    p.name = body.name
    audit(db, "human", "rename", f"project:{p.id}", {"name": body.name})
    db.commit()
    return {"id": p.id, "name": p.name}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """项目删除：仅当其下无已发布模块时允许，否则 409 提示先归档模块。
    删除时级联硬删全部 大业务/文档/草稿模块/版本历史，并一并删除绑定到
    该项目的 API key（避免遗留 key 失效语义不清）。"""
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
    for domain in p.domains:
        for doc in domain.documents:
            _hard_delete_document(db, doc)  # raises 409 if any published module
        db.delete(domain)
    bound_keys = db.query(ApiKey).filter(ApiKey.project_id == p.id).all()
    bound_humans = sum(1 for k in bound_keys if k.prefix == "human")
    total_humans = db.query(ApiKey).filter(ApiKey.prefix == "human").count()
    if bound_humans and total_humans - bound_humans < 1:
        raise HTTPException(
            status_code=409,
            detail="删除该项目会连带删除最后一把 human key，删除后无人能管理系统，已拒绝",
        )
    for k in bound_keys:
        db.delete(k)
    audit(db, "human", "delete", f"project:{p.id}",
          {"name": p.name, "deleted_keys": len(bound_keys)})
    db.delete(p)
    db.commit()
    return {"id": project_id, "deleted": True, "deleted_keys": len(bound_keys)}


@router.post("/domains", status_code=201)
def create_domain(body: DomainCreate, db: Session = Depends(get_db)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    d = Domain(project_id=body.project_id, name=body.name)
    db.add(d)
    db.commit()
    return {"id": d.id, "name": d.name}


@router.put("/domains/{domain_id}")
def rename_domain(domain_id: int, body: RenameRequest, db: Session = Depends(get_db)):
    d = db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status_code=404, detail="domain not found")
    d.name = body.name
    audit(db, "human", "rename", f"domain:{d.id}", {"name": body.name})
    db.commit()
    return {"id": d.id, "name": d.name}


def _hard_delete_block(db: Session, block: Block) -> None:
    db.query(BlockVersion).filter(BlockVersion.block_id == block.id).delete()
    db.query(Ack).filter(Ack.block_id == block.id).delete()
    db.query(Proposal).filter(Proposal.block_id == block.id).delete()
    db.delete(block)


def _hard_delete_document(db: Session, doc: Document) -> None:
    published = [b for b in doc.blocks if b.status == "published"]
    if published:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "文档下仍有已发布模块，请先归档这些模块再删除文档",
                "published_blocks": [{"id": b.id, "title": b.title} for b in published],
            },
        )
    for b in doc.blocks:
        _hard_delete_block(db, b)
    db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).delete()
    db.delete(doc)


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: int, db: Session = Depends(get_db)):
    """大业务删除：仅当其下无已发布模块时允许，否则 409 提示先归档模块。"""
    d = db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status_code=404, detail="domain not found")
    for doc in d.documents:
        _hard_delete_document(db, doc)  # raises 409 if any published module
    audit(db, "human", "delete", f"domain:{d.id}", {"name": d.name})
    db.delete(d)
    db.commit()
    return {"id": domain_id, "deleted": True}


@router.post("/documents", status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(get_db)):
    if db.get(Domain, body.domain_id) is None:
        raise HTTPException(status_code=404, detail="domain not found")
    doc = Document(domain_id=body.domain_id, title=body.title, doc_type=body.doc_type)
    db.add(doc)
    db.commit()
    return {"id": doc.id, "title": doc.title}


@router.put("/documents/{document_id}")
def rename_document(document_id: int, body: RenameRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    doc.title = body.name
    audit(db, "human", "rename", f"document:{doc.id}", {"title": body.name})
    db.commit()
    return {"id": doc.id, "title": doc.title}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """文档删除：仅当其下无已发布模块时允许，否则 409 提示先归档模块。"""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    audit(db, "human", "delete", f"document:{doc.id}", {"title": doc.title})
    _hard_delete_document(db, doc)
    db.commit()
    return {"id": document_id, "deleted": True}


# ---------- block (module) CRUD — draft ----------


@router.post("/blocks", status_code=201)
def create_block(body: BlockCreate, db: Session = Depends(get_db)):
    if db.get(Document, body.document_id) is None:
        raise HTTPException(status_code=404, detail="document not found")
    apis = _validate_apis_or_422([e.model_dump() for e in body.apis])
    rules = _validate_rules_or_422([e.model_dump() for e in body.rules])
    block = Block(
        document_id=body.document_id,
        title=body.title,
        summary=body.summary,
        draft_content_md=body.content_md,
        draft_rules_json=json.dumps(rules, ensure_ascii=False),
        draft_apis_json=json.dumps(apis, ensure_ascii=False),
        draft_nfr_md=body.nfr_md,
    )
    db.add(block)
    db.commit()
    return {"id": block.id, "title": block.title, "status": block.status}


@router.get("/blocks/{block_id}/draft")
def get_draft(block_id: int, db: Session = Depends(get_db)):
    """Human-only view of the working draft. Never exposed to agents."""
    block = _get_block(db, block_id)
    return {
        "id": block.id,
        "document_id": block.document_id,
        "title": block.title,
        "summary": block.summary,
        "status": block.status,
        "current_published_version": block.current_published_version,
        "content_md": block.draft_content_md,
        "rules": json.loads(block.draft_rules_json or "[]"),
        "apis": json.loads(block.draft_apis_json or "[]"),
        "nfr_md": block.draft_nfr_md,
    }


@router.put("/blocks/{block_id}")
def update_block(block_id: int, body: BlockUpdate, db: Session = Depends(get_db)):
    block = _get_block(db, block_id)
    if body.title is not None:
        block.title = body.title
    if body.summary is not None:
        block.summary = body.summary
    if body.content_md is not None:
        block.draft_content_md = body.content_md
    if body.rules is not None:
        rules = _validate_rules_or_422([e.model_dump() for e in body.rules])
        block.draft_rules_json = json.dumps(rules, ensure_ascii=False)
    if body.apis is not None:
        apis = _validate_apis_or_422([e.model_dump() for e in body.apis])
        block.draft_apis_json = json.dumps(apis, ensure_ascii=False)
    if body.nfr_md is not None:
        block.draft_nfr_md = body.nfr_md
    db.commit()
    return {"id": block.id, "status": block.status}


@router.delete("/blocks/{block_id}")
def delete_block(block_id: int, db: Session = Depends(get_db)):
    """删除语义：草稿态直接删除；已发布模块删除 = 归档（agent 读不到、index
    不出现，历史版本保留可查）。归档是模块集合结构变更，立即派生文档新
    版本（MINOR）：新 manifest 不再包含该模块；pin 旧文档版本仍见历史快照。"""
    block = _get_block(db, block_id)
    if block.status == "draft":
        _hard_delete_block(db, block)
        audit(db, "human", "delete", f"block:{block_id}", {"title": block.title})
        db.commit()
        return {"id": block_id, "deleted": True}
    block.status = "archived"
    block.archived_at = utcnow()
    audit(db, "human", "archive", f"block:{block.id}", {})
    doc_version = _derive_document_version(
        db, block, "minor", "human", f"归档模块「{block.title}」"
    )
    db.commit()
    return {"id": block.id, "status": block.status, "document_version": doc_version}


@router.delete("/blocks/{block_id}/purge")
def purge_block(block_id: int, db: Session = Depends(get_db)):
    """彻底删除：仅允许对已归档模块执行。硬删模块及其全部版本历史，
    不可恢复。"""
    block = _get_block(db, block_id)
    if block.status != "archived":
        raise HTTPException(
            status_code=409, detail="只有已归档的模块才能彻底删除（请先归档）"
        )
    _hard_delete_block(db, block)
    audit(db, "human", "purge", f"block:{block_id}", {"title": block.title})
    db.commit()
    return {"id": block_id, "purged": True}


@router.post("/blocks/{block_id}/restore")
def restore_block(block_id: int, db: Session = Depends(get_db)):
    """恢复已归档模块：重新进入已发布状态（历史版本从未丢失）。恢复同样是
    模块集合结构变更，立即派生文档新版本（MINOR），模块回到 manifest。"""
    block = _get_block(db, block_id)
    if block.status != "archived":
        raise HTTPException(status_code=409, detail=f"block is {block.status}, not archived")
    block.status = "published"
    block.archived_at = None
    audit(db, "human", "restore", f"block:{block.id}", {})
    doc_version = _derive_document_version(
        db, block, "minor", "human", f"恢复模块「{block.title}」"
    )
    db.commit()
    return {"id": block.id, "status": block.status,
            "current_published_version": block.current_published_version,
            "document_version": doc_version}


# ---------- 完成标记 ----------


@router.post("/blocks/{block_id}/complete")
def complete_block(block_id: int, db: Session = Depends(get_db)):
    """标记完成：当前已发布版本已被实现完成。权威状态由人驱动；ack 是 AI 的
    单次回执，两者不自动联动。"""
    block = _get_block(db, block_id)
    if block.status != "published" or block.current_published_version is None:
        raise HTTPException(status_code=409, detail="只有已发布的模块才能标记完成")
    block.completed = True
    block.completed_version = block.current_published_version
    block.completed_at = utcnow()
    audit(db, "human", "complete", f"block:{block.id}@{block.completed_version}", {})
    db.commit()
    return {"id": block.id, "completed": True, "completed_version": block.completed_version}


@router.post("/blocks/{block_id}/uncomplete")
def uncomplete_block(block_id: int, db: Session = Depends(get_db)):
    block = _get_block(db, block_id)
    block.completed = False
    audit(db, "human", "uncomplete", f"block:{block.id}", {})
    db.commit()
    return {"id": block.id, "completed": False, "completed_version": block.completed_version}


# ---------- publish / versions ----------


@router.post("/blocks/{block_id}/publish")
def publish(
    block_id: int,
    body: PublishRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    block = _get_block(db, block_id)
    return publish_block(
        db,
        block,
        actor=key.hint,
        change_note=body.change_note,
        fast_track=body.fastTrack,
        confirm=body.confirm,
        dry_run=body.dryRun,
    )


@router.get("/blocks/{block_id}/versions")
def list_versions(block_id: int, db: Session = Depends(get_db)):
    block = _get_block(db, block_id)
    return [
        {
            "version": v.version,
            "change_note": v.change_note,
            "delta": json.loads(v.delta_json),
            "published_by": v.published_by,
            "published_at": v.published_at,
        }
        for v in block.versions
    ]


@router.get("/documents/{document_id}/versions")
def list_document_versions(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return [
        {
            "version": v.version,
            "manifest": json.loads(v.manifest_json),
            "triggered_by_block_id": v.triggered_by_block_id,
            "change_note": v.change_note,
            "published_by": v.published_by,
            "published_at": v.published_at,
        }
        for v in doc.versions
    ]


# ---------- proposals (human review queue) ----------


@router.get("/proposals")
def list_proposals(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Proposal)
    if status:
        q = q.filter(Proposal.status == status)
    return [
        {
            "id": p.id,
            "block_id": p.block_id,
            "block_title": db.get(Block, p.block_id).title,
            "author_type": p.author_type,
            "description": p.description,
            "suggestion": p.suggestion,
            "scenario": p.scenario,
            "status": p.status,
            "resolution_note": p.resolution_note,
            "published_version": p.published_version,
            "created_at": p.created_at,
        }
        for p in q.order_by(Proposal.id.desc()).all()
    ]


@router.post("/proposals/{proposal_id}/resolve")
def resolve_proposal(
    proposal_id: int,
    body: ResolveRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    if p.status != "submitted":
        raise HTTPException(status_code=409, detail=f"proposal already {p.status}")

    if body.action == "reject":
        p.status = "rejected"
        p.resolution_note = body.resolution_note
        p.resolved_at = utcnow()
        audit(db, key.hint, "proposal_resolve", f"proposal:{p.id}", {"action": "reject"})
        db.commit()
        return {"id": p.id, "status": p.status}

    # approve: apply the proposal's rewrite to the draft, then publish it.
    # Human approval is itself the confirmation, so breaking diffs publish.
    block = _get_block(db, p.block_id)
    if p.proposed_content_md is not None:
        block.draft_content_md = p.proposed_content_md
    if p.proposed_apis_json is not None:
        block.draft_apis_json = p.proposed_apis_json
    result = publish_block(
        db,
        block,
        actor=key.hint,
        change_note=body.resolution_note or f"proposal #{p.id}: {p.description}",
        fast_track=False,
        confirm=True,
    )
    p.status = "published"
    p.resolution_note = body.resolution_note
    p.published_version = result.version
    p.resolved_at = utcnow()
    audit(
        db,
        key.hint,
        "proposal_resolve",
        f"proposal:{p.id}",
        {"action": "approve", "published_version": result.version},
    )
    db.commit()
    return {
        "id": p.id,
        "status": p.status,
        "published_version": result.version,
        "document_version": result.document_version,
    }


# ---------- ack board ----------


@router.get("/acks")
def list_acks(db: Session = Depends(get_db)):
    return [
        {
            "id": a.id,
            "block_id": a.block_id,
            "block_title": db.get(Block, a.block_id).title,
            "version": a.version,
            "agent_key": a.agent_key,
            "task_desc": a.task_desc,
            "created_at": a.created_at,
        }
        for a in db.query(Ack).order_by(Ack.id.desc()).all()
    ]


# ---------- API key management (用户/密钥管理) ----------


def _key_out(k: ApiKey) -> dict:
    """列表视图：绝不含明文，也不含哈希，只给展示用 hint。"""
    return {
        "id": k.id,
        "hint": k.hint,
        "prefix": k.prefix,
        "label": k.label,
        "project_id": k.project_id,
        "created_at": k.created_at,
    }


@router.get("/keys")
def list_keys(db: Session = Depends(get_db)):
    return [_key_out(k) for k in db.query(ApiKey).order_by(ApiKey.id).all()]


@router.post("/keys", status_code=201)
def create_key(body: KeyCreate, db: Session = Depends(get_db)):
    if body.project_id is not None and db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    plaintext = new_key(body.prefix)
    k = ApiKey(key=hash_key(plaintext), hint=key_hint(plaintext),
               prefix=body.prefix, project_id=body.project_id, label=body.label)
    db.add(k)
    audit(db, "human", "key_create", f"apikey:{k.hint}", {"prefix": k.prefix, "label": k.label})
    db.commit()
    # 明文仅此一次返回，此后任何地方（列表/UI/审计）都不可再见
    return {**_key_out(k), "key": plaintext,
            "notice": "此 key 仅此一次可见，请立即复制保存；系统只存哈希，无法找回"}


@router.delete("/keys/{key_id}")
def delete_key(key_id: int, db: Session = Depends(get_db)):
    k = db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(status_code=404, detail="key not found")
    if k.prefix == "human":
        humans = db.query(ApiKey).filter(ApiKey.prefix == "human").count()
        if humans <= 1:
            raise HTTPException(
                status_code=409,
                detail="这是最后一把 human key，删除后无人能管理系统，已拒绝",
            )
    audit(db, "human", "key_delete", f"apikey:{k.hint}", {"prefix": k.prefix, "label": k.label})
    db.delete(k)
    db.commit()
    return {"id": key_id, "deleted": True}
