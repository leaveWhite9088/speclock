"""Agent (read-only + proposal) API — requires an ``agent-*`` key.

There is deliberately NO write endpoint here that can alter documents. The
only mutations an agent can cause are Proposal and Ack rows, which live
outside the published document store. Drafts are never reachable from this
router.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from speclock import diffing
from speclock.auth import audit, require_agent
from speclock.db import get_db
from speclock.models import (
    Ack,
    ApiKey,
    Block,
    BlockVersion,
    Document,
    DocumentVersion,
    Proposal,
)
from speclock.schemas import (
    AckRequest,
    BlockOut,
    DocumentIndexEntry,
    DocumentOut,
    IndexEntry,
    ProposalCreate,
    ProposalOut,
)

router = APIRouter(prefix="/api/v1", tags=["agent"])

REF_RE = re.compile(r"^(?P<id>\d+)(?:@(?P<version>\d+\.\d+\.\d+))?$")


def _published_snapshot(db: Session, block: Block, version: str | None) -> BlockVersion:
    if block.status != "published":
        # drafts and archived blocks are invisible to agents
        raise HTTPException(status_code=404, detail=f"block {block.id} not found")
    target = version or block.current_published_version
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == target)
        .first()
    )
    if bv is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {target}")
    return bv


def _block_out(bv: BlockVersion) -> BlockOut:
    return BlockOut(
        block_id=bv.block_id,
        title=bv.block.title,
        version=bv.version,
        content_md=bv.content_md,
        apis=json.loads(bv.apis_json or "[]"),
        openapi_yaml=bv.openapi_yaml,
        nfr_md=bv.nfr_md,
        change_note=bv.change_note,
        delta=json.loads(bv.delta_json),
        published_at=bv.published_at,
    )


@router.get("/index", response_model=list[IndexEntry])
def get_index(db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """One-line summary per published module. Contract: response body <= 8KB."""
    entries = []
    for block in db.query(Block).filter(Block.status == "published").all():
        doc = block.document
        entries.append(
            IndexEntry(
                block_id=block.id,
                title=block.title,
                domain=doc.domain.name,
                document=doc.title,
                version=block.current_published_version,
                summary=(block.summary or block.draft_content_md.strip())[:50],
            )
        )
    audit(db, key.key, "pull", "index", {"entries": len(entries)})
    db.commit()
    return entries


@router.get("/blocks/{ref}", response_model=BlockOut)
def get_block(ref: str, db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """Read a published module snapshot. ``ref`` is ``{id}`` or ``{id}@{x.y.z}`` (pin)."""
    m = REF_RE.match(ref)
    if not m:
        raise HTTPException(
            status_code=400, detail="ref must be '{id}' or '{id}@{MAJOR.MINOR.PATCH}'"
        )
    block = db.get(Block, int(m.group("id")))
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {ref} not found")
    bv = _published_snapshot(db, block, m.group("version"))
    audit(db, key.key, "pull", f"block:{block.id}@{bv.version}", {})
    db.commit()
    return _block_out(bv)


@router.get("/blocks/{block_id}/diff")
def get_diff(
    block_id: int,
    from_: str = Query(alias="from"),
    to: str = Query(),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_agent),
):
    block = db.get(Block, block_id)
    if block is None or block.status != "published":
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    old = _published_snapshot(db, block, from_)
    new = _published_snapshot(db, block, to)
    d = diffing.delta(json.loads(old.apis_json or "[]"), json.loads(new.apis_json or "[]"))
    audit(db, key.key, "pull", f"block:{block_id}/diff", {"from": from_, "to": to})
    db.commit()
    return {
        "block_id": block_id,
        "from": from_,
        "to": to,
        "content_diff": diffing.text_diff(
            old.content_md, new.content_md, fromfile=from_, tofile=to
        ),
        "openapi_diff": diffing.text_diff(
            old.openapi_yaml, new.openapi_yaml, fromfile=from_, tofile=to
        ),
        "delta": d,
        "breaking": diffing.is_breaking(d),
    }


# ---------- document-level reads (两级版本的文档侧) ----------


def _document_out(dv: DocumentVersion) -> DocumentOut:
    manifest = json.loads(dv.manifest_json)
    return DocumentOut(
        document_id=dv.document_id,
        title=dv.document.title,
        version=dv.version,
        manifest=[
            {"block_id": int(bid), "title": m["title"], "version": m["version"]}
            for bid, m in manifest.items()
        ],
        published_at=dv.published_at,
    )


@router.get("/documents", response_model=list[DocumentIndexEntry])
def get_documents(db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """文档列表 + 当前文档版本。没有任何已发布模块的文档对 agent 不可见。"""
    out = []
    for doc in db.query(Document).all():
        if doc.current_version is None:
            continue
        out.append(
            DocumentIndexEntry(
                document_id=doc.id,
                title=doc.title,
                domain=doc.domain.name,
                doc_type=doc.doc_type,
                version=doc.current_version,
            )
        )
    audit(db, key.key, "pull", "documents", {"entries": len(out)})
    db.commit()
    return out


@router.get("/documents/{ref}", response_model=DocumentOut)
def get_document(ref: str, db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """文档 manifest：该文档全部模块当前已发布版本清单。支持 ``{id}@{x.y.z}`` pin。"""
    m = REF_RE.match(ref)
    if not m:
        raise HTTPException(
            status_code=400, detail="ref must be '{id}' or '{id}@{MAJOR.MINOR.PATCH}'"
        )
    doc = db.get(Document, int(m.group("id")))
    if doc is None or doc.current_version is None:
        raise HTTPException(status_code=404, detail=f"document {ref} not found")
    target = m.group("version") or doc.current_version
    dv = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc.id, DocumentVersion.version == target)
        .first()
    )
    if dv is None:
        raise HTTPException(status_code=404, detail=f"document {doc.id} has no version {target}")
    audit(db, key.key, "pull", f"document:{doc.id}@{dv.version}", {})
    db.commit()
    return _document_out(dv)


# ---------- ack & proposals (agent's only writes) ----------


@router.post("/blocks/{block_id}/ack", status_code=201)
def ack_block(
    block_id: int,
    body: AckRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_agent),
):
    """Agent receipt: 'implemented against this exact published version'."""
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    _published_snapshot(db, block, body.version)  # must be a real published version
    ack = Ack(block_id=block_id, version=body.version, agent_key=key.key, task_desc=body.task_desc)
    db.add(ack)
    audit(db, key.key, "ack", f"block:{block_id}@{body.version}", {"task_desc": body.task_desc})
    db.commit()
    return {"id": ack.id, "block_id": block_id, "version": body.version}


@router.post("/proposals", status_code=201)
def submit_proposal(
    body: ProposalCreate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_agent),
):
    """The ONLY write outlet for agents. Proposals never touch the main store
    until a human approves and publishes them via the admin API."""
    block = db.get(Block, body.block_id)
    if block is None or block.status != "published":
        raise HTTPException(status_code=404, detail=f"block {body.block_id} not found")
    proposed_apis_json = None
    if body.proposed_apis is not None:
        try:
            normalized = diffing.validate_apis([e.model_dump() for e in body.proposed_apis])
        except diffing.ApisValidationError as exc:
            raise HTTPException(status_code=422, detail=f"API 列表不合法: {exc}") from exc
        proposed_apis_json = json.dumps(normalized, ensure_ascii=False)
    p = Proposal(
        block_id=body.block_id,
        author_type="agent",
        description=body.description,
        suggestion=body.suggestion,
        scenario=body.scenario,
        proposed_content_md=body.proposed_content_md,
        proposed_apis_json=proposed_apis_json,
    )
    db.add(p)
    db.flush()
    audit(
        db,
        key.key,
        "proposal_submit",
        f"proposal:{p.id}",
        {"block_id": body.block_id, "description": body.description},
    )
    db.commit()
    return {"id": p.id, "status": p.status}


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
def get_proposal(
    proposal_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)
):
    """Polling endpoint for agents awaiting a decision."""
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return p
