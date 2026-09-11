"""Minimal human-facing UI (Jinja2 + vanilla JS).

Pages: document tree, module editor (业务描述 / API 填表区 / 非功能性需求
三区，全程无 YAML), diff view, publish, proposal inbox, ack board,
document version history. Auth via ?key=human-... query parameter — MVP
grade, single-operator tool.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from speclock.db import get_db
from speclock.models import (
    Ack,
    Block,
    Document,
    DocumentVersion,
    Domain,
    Project,
    Proposal,
)

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _check_key(request: Request, db: Session) -> str | RedirectResponse:
    key = request.query_params.get("key", "")
    if not key.startswith("human-"):
        return RedirectResponse(url="/ui/login")
    return key


@router.get("/ui/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def tree(request: Request, db: Session = Depends(get_db)):
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    projects = db.query(Project).all()
    domains = db.query(Domain).all()
    return templates.TemplateResponse(
        request, "tree.html", {"key": key, "projects": projects, "domains": domains}
    )


@router.get("/ui/documents/{document_id}", response_class=HTMLResponse)
def document_page(document_id: int, request: Request, db: Session = Depends(get_db)):
    """文档页：文档版本历史 + 每个版本的模块版本清单（manifest）。"""
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    doc = db.get(Document, document_id)
    versions = [
        {
            "version": v.version,
            "manifest": json.loads(v.manifest_json),
            "triggered_by_block_id": v.triggered_by_block_id,
            "change_note": v.change_note,
            "published_at": v.published_at,
        }
        for v in reversed(doc.versions)
    ]
    return templates.TemplateResponse(
        request,
        "document.html",
        {"key": key, "doc": doc, "versions": versions},
    )


@router.get("/ui/blocks/{block_id}", response_class=HTMLResponse)
def editor(block_id: int, request: Request, db: Session = Depends(get_db)):
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    block = db.get(Block, block_id)
    versions = [
        {"version": v.version, "change_note": v.change_note, "published_at": v.published_at}
        for v in block.versions
    ]
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "key": key,
            "block": block,
            "versions": versions,
            "apis": json.loads(block.draft_apis_json or "[]"),
        },
    )


@router.get("/ui/blocks/{block_id}/view", response_class=HTMLResponse)
def block_view(
    block_id: int,
    request: Request,
    version: str = "",
    api: int | None = None,
    db: Session = Depends(get_db),
):
    """模块查看页（只读，看已发布版本）：API 列表 + 单条 API 详情视图。"""
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    block = db.get(Block, block_id)
    from speclock.models import BlockVersion

    target = version or block.current_published_version
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == target)
        .first()
    )
    apis = json.loads(bv.apis_json or "[]") if bv else []
    detail = None
    if api is not None and 0 <= api < len(apis):
        detail = (api, apis[api])
    return templates.TemplateResponse(
        request,
        "view.html",
        {
            "key": key,
            "block": block,
            "bv": bv,
            "apis": apis,
            "detail": detail,
            "versions": [v.version for v in block.versions],
        },
    )


@router.get("/ui/blocks/{block_id}/diff", response_class=HTMLResponse)
def diff_view(
    block_id: int,
    request: Request,
    from_: str = Query(default="", alias="from"),
    to: str = "",
    db: Session = Depends(get_db),
):
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    block = db.get(Block, block_id)
    from speclock import diffing

    versions = {v.version: v for v in block.versions}
    diff_text = ""
    delta = {"added": [], "modified": [], "removed": []}
    if from_ in versions and to in versions:
        old, new = versions[from_], versions[to]
        diff_text = diffing.text_diff(old.content_md, new.content_md, from_, to)
        delta = diffing.delta(
            json.loads(old.apis_json or "[]"), json.loads(new.apis_json or "[]")
        )
    return templates.TemplateResponse(
        request,
        "diff.html",
        {
            "key": key,
            "block": block,
            "versions": sorted(versions),
            "from": from_,
            "to": to,
            "diff_text": diff_text,
            "delta": delta,
        },
    )


@router.get("/ui/proposals", response_class=HTMLResponse)
def proposals(request: Request, db: Session = Depends(get_db)):
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    props = db.query(Proposal).order_by(Proposal.id.desc()).all()
    rows = [
        (p, db.get(Block, p.block_id), json.loads(p.proposed_apis_json)
         if p.proposed_apis_json else None)
        for p in props
    ]
    return templates.TemplateResponse(
        request, "proposals.html", {"key": key, "rows": rows}
    )


@router.get("/ui/acks", response_class=HTMLResponse)
def acks(request: Request, db: Session = Depends(get_db)):
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    rows = [(a, db.get(Block, a.block_id)) for a in db.query(Ack).order_by(Ack.id.desc()).all()]
    return templates.TemplateResponse(request, "acks.html", {"key": key, "rows": rows})
