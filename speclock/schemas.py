"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- admin (human) requests ----------


class BlockCreate(BaseModel):
    document_id: int
    title: str
    summary: str = ""
    content_md: str = ""
    openapi_yaml: str = ""
    nfr_md: str = ""


class BlockUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    content_md: str | None = None
    openapi_yaml: str | None = None
    nfr_md: str | None = None


class PublishRequest(BaseModel):
    change_note: str = ""
    fastTrack: bool = False
    confirm: bool = False  # required when the diff is breaking


class ResolveRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    resolution_note: str = ""


class DocumentCreate(BaseModel):
    domain_id: int
    title: str
    doc_type: str = "business"


class DomainCreate(BaseModel):
    project_id: int
    name: str


class ProjectCreate(BaseModel):
    name: str


# ---------- agent requests ----------


class AckRequest(BaseModel):
    version: str
    task_desc: str = ""


class ProposalCreate(BaseModel):
    block_id: int
    description: str
    suggestion: str
    scenario: str = ""
    proposed_content_md: str | None = None
    proposed_openapi_yaml: str | None = None


# ---------- responses ----------


class IndexEntry(BaseModel):
    block_id: int
    title: str
    domain: str
    document: str
    version: str
    summary: str  # <= 50 chars


class Delta(BaseModel):
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []


class BlockOut(BaseModel):
    block_id: int
    title: str
    version: str
    content_md: str
    openapi_yaml: str
    nfr_md: str
    change_note: str
    delta: Delta
    published_at: datetime | None


class PublishResult(BaseModel):
    block_id: int
    version: str
    delta: Delta
    breaking: bool
    affected: list[str] = []


class ProposalOut(BaseModel):
    id: int
    block_id: int
    author_type: str
    description: str
    suggestion: str
    scenario: str
    status: str
    resolution_note: str
    published_version: str | None
    created_at: datetime
    resolved_at: datetime | None
