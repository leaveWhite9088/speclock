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
from speclock.auth import audit, require_human
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
    ProjectCreate,
    PublishRequest,
    PublishResult,
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
) -> PublishResult:
    """Snapshot the working draft into a new immutable BlockVersion, then
    derive a new DocumentVersion for the owning document.

    fastTrack is only legal for non-breaking diffs; breaking diffs require
    confirm=true and always report the affected field list.
    """
    apis = _validate_apis_or_422(json.loads(block.draft_apis_json or "[]"))

    old_apis: list = []
    if block.current_published_version is not None:
        old_apis = json.loads(
            _published_version(db, block, block.current_published_version).apis_json or "[]"
        )
    d = diffing.delta(old_apis, apis)
    breaking = diffing.is_breaking(d)
    affected = d["removed"] + d["modified"]

    if breaking and fast_track:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "fastTrack rejected: diff contains breaking changes",
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

    version, level = diffing.next_module_version(block.current_published_version, d)
    bv = BlockVersion(
        block_id=block.id,
        version=version,
        content_md=block.draft_content_md,
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
    )


# ---------- taxonomy CRUD ----------


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=body.name)
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name}


@router.post("/domains", status_code=201)
def create_domain(body: DomainCreate, db: Session = Depends(get_db)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    d = Domain(project_id=body.project_id, name=body.name)
    db.add(d)
    db.commit()
    return {"id": d.id, "name": d.name}


@router.post("/documents", status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(get_db)):
    if db.get(Domain, body.domain_id) is None:
        raise HTTPException(status_code=404, detail="domain not found")
    doc = Document(domain_id=body.domain_id, title=body.title, doc_type=body.doc_type)
    db.add(doc)
    db.commit()
    return {"id": doc.id, "title": doc.title}


# ---------- block (module) CRUD — draft ----------


@router.post("/blocks", status_code=201)
def create_block(body: BlockCreate, db: Session = Depends(get_db)):
    if db.get(Document, body.document_id) is None:
        raise HTTPException(status_code=404, detail="document not found")
    apis = _validate_apis_or_422([e.model_dump() for e in body.apis])
    block = Block(
        document_id=body.document_id,
        title=body.title,
        summary=body.summary,
        draft_content_md=body.content_md,
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
    if body.apis is not None:
        apis = _validate_apis_or_422([e.model_dump() for e in body.apis])
        block.draft_apis_json = json.dumps(apis, ensure_ascii=False)
    if body.nfr_md is not None:
        block.draft_nfr_md = body.nfr_md
    db.commit()
    return {"id": block.id, "status": block.status}


@router.delete("/blocks/{block_id}")
def archive_block(block_id: int, db: Session = Depends(get_db)):
    """Archive = stop distribution. Agents lose read access immediately."""
    block = _get_block(db, block_id)
    block.status = "archived"
    audit(db, "human", "archive", f"block:{block.id}", {})
    db.commit()
    return {"id": block.id, "status": block.status}


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
        actor=key.key,
        change_note=body.change_note,
        fast_track=body.fastTrack,
        confirm=body.confirm,
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
        audit(db, key.key, "proposal_resolve", f"proposal:{p.id}", {"action": "reject"})
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
        actor=key.key,
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
        key.key,
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
