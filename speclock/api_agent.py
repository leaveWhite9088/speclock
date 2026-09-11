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
from speclock.models import Ack, ApiKey, Block, BlockVersion, Proposal
from speclock.schemas import AckRequest, BlockOut, IndexEntry, ProposalCreate, ProposalOut

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
        openapi_yaml=bv.openapi_yaml,
        nfr_md=bv.nfr_md,
        change_note=bv.change_note,
        delta=json.loads(bv.delta_json),
        published_at=bv.published_at,
    )


@router.get("/index", response_model=list[IndexEntry])
def get_index(db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """One-line summary per published block. Contract: response body <= 8KB."""
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
    return entries


@router.get("/blocks/{ref}", response_model=BlockOut)
def get_block(ref: str, db: Session = Depends(get_db), key: ApiKey = Depends(require_agent)):
    """Read a published snapshot. ``ref`` is ``{id}`` or ``{id}@{x.y.z}`` (pin)."""
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
        "delta": diffing.delta(old.openapi_yaml, new.openapi_yaml),
        "breaking": diffing.is_breaking(diffing.delta(old.openapi_yaml, new.openapi_yaml)),
    }


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
    if body.proposed_openapi_yaml is not None:
        try:
            diffing.validate_openapi_fragment(body.proposed_openapi_yaml)
        except diffing.OpenAPIValidationError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid OpenAPI fragment: {exc}"
            ) from exc
    p = Proposal(
        block_id=body.block_id,
        author_type="agent",
        description=body.description,
        suggestion=body.suggestion,
        scenario=body.scenario,
        proposed_content_md=body.proposed_content_md,
        proposed_openapi_yaml=body.proposed_openapi_yaml,
    )
    db.add(p)
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
