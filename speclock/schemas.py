"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- structured API entries (编辑与 diff 的真相源) ----------


class ApiField(BaseModel):
    """递归字段模型：object/array 类型可携带 children 子字段。"""

    name: str
    type: str  # string|number|integer|boolean|array|object（语义校验在 diffing）
    required: bool = False
    description: str = ""
    children: list["ApiField"] = []


class ApiEntry(BaseModel):
    name: str  # 中文显示名
    api: str  # 方法 + 路径，如 "GET /api/daily-report"
    request: list[ApiField] = []
    response: list[ApiField] = []


# ---------- admin (human) requests ----------


class BlockCreate(BaseModel):
    document_id: int
    title: str
    summary: str = ""
    content_md: str = ""
    apis: list[ApiEntry] = []
    nfr_md: str = ""


class BlockUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    content_md: str | None = None
    apis: list[ApiEntry] | None = None
    nfr_md: str | None = None


class PublishRequest(BaseModel):
    change_note: str = ""
    fastTrack: bool = False
    confirm: bool = False  # required when the diff is breaking


class ResolveRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    resolution_note: str = ""


class RenameRequest(BaseModel):
    name: str


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
    proposed_apis: list[ApiEntry] | None = None


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
    apis: list[dict]  # 结构化 API 列表（真相源）
    openapi_yaml: str  # 发布时生成的 OpenAPI 3.x（机器消费）
    nfr_md: str
    change_note: str
    delta: Delta
    published_at: datetime | None


class PublishResult(BaseModel):
    block_id: int
    version: str
    document_id: int
    document_version: str  # 本次发布派生的文档版本
    delta: Delta
    breaking: bool
    affected: list[str] = []


class DocumentIndexEntry(BaseModel):
    document_id: int
    title: str
    domain: str
    doc_type: str
    version: str  # 当前文档版本


class DocumentOut(BaseModel):
    document_id: int
    title: str
    version: str
    manifest: list[dict]  # [{block_id, title, version}]
    published_at: datetime | None


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
