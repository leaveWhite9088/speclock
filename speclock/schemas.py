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
    desc: str = ""  # 端点语义：谁调用、为什么、副作用/幂等等字段表看不出来的信息
    request: list[ApiField] = []
    response: list[ApiField] = []


class RuleEntry(BaseModel):
    """结构化业务规则：规则名 + 规则详述。"""

    name: str
    detail: str


# ---------- admin (human) requests ----------


class BlockCreate(BaseModel):
    document_id: int
    title: str
    summary: str = ""
    content_md: str = ""
    rules: list[RuleEntry] = []
    edge_md: str = ""
    apis: list[ApiEntry] = []
    nfr_md: str = ""


class BlockUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    content_md: str | None = None
    rules: list[RuleEntry] | None = None
    edge_md: str | None = None
    apis: list[ApiEntry] | None = None
    nfr_md: str | None = None


class PublishRequest(BaseModel):
    change_note: str = ""
    fastTrack: bool = False
    confirm: bool = False  # required when the diff is breaking
    dryRun: bool = False  # 预览：返回将发布的版本/delta/破坏性，不落库


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


class KeyCreate(BaseModel):
    prefix: str = Field(pattern="^(human|agent)$")
    label: str = ""
    # 项目隔离：绑定项目后 agent key 只能读该项目文档；None = 全局可见。
    # 仅对 agent key 生效（human key 是管理端，始终全局）。
    project_id: int | None = None


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


class IndexBlock(BaseModel):
    block_id: int
    title: str
    version: str
    summary: str  # <= 50 chars
    completed: bool  # 当前已发布版本是否已被实现完成
    completed_version: str | None  # 上次完成对应的版本号


class IndexDocument(BaseModel):
    document_id: int
    title: str
    version: str | None  # 当前文档版本
    blocks: list[IndexBlock]


class IndexDomain(BaseModel):
    domain: str
    documents: list[IndexDocument]


class Delta(BaseModel):
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    # 规则清单 delta（按 rule name 匹配；rules 变化不算破坏性）
    rules_added: list[str] = []
    rules_removed: list[str] = []
    rules_modified: list[str] = []


class BlockOut(BaseModel):
    block_id: int
    title: str
    version: str
    content_md: str
    rules: list[dict]  # 结构化业务规则清单 [{name, detail}]
    edge_md: str  # 边界与异常（可空）
    apis: list[dict]  # 结构化 API 列表（真相源，条目带 desc 端点语义）
    openapi_yaml: str  # 发布时生成的 OpenAPI 3.x（机器消费）
    nfr_md: str
    change_note: str
    delta: Delta
    published_at: datetime | None
    completed: bool
    completed_version: str | None


class PublishResult(BaseModel):
    block_id: int
    version: str
    document_id: int
    document_version: str  # 本次发布派生的文档版本（dryRun 时为预测值）
    delta: Delta
    breaking: bool
    affected: list[str] = []
    groups: list[dict] = []  # 按 API 分组的结构化 delta（确认视图用）


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
