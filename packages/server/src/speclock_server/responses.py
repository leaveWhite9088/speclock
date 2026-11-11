"""对外接口的响应声明：每个接口返回的 JSON 形状。

这些模型有三个用处：

1. 接口文档（``/docs``、``/openapi.json``）里能看到返回结构；
2. 服务端在返回前按它校验——字段缺了、类型不对会直接 500，而不是悄悄把错的形状交出去；
3. ``tests/test_openapi_contract.py`` 把整份 OpenAPI 和 ``docs/openapi.json`` 比对，形状变了测试就失败。

约定：

- 字段一律**必填**（没有默认值），除非该字段本来就可能不出现；"可能为空"写成 ``X | None``（值是 null，键仍在）。
- 模型 ``extra="forbid"``：处理函数多返回了没声明的字段，也会在测试里报出来，而不是被悄悄丢掉。
- 改了这里的字段 = 改了对外接口：更新 ``docs/openapi.json``，并在 CHANGELOG 记一条。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from speclock_core import BlockOut, Delta


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------- 通用 ----------


class ErrorOut(Out):
    """所有错误响应的形状。``detail`` 是给人看的文本（部分错误是带结构的对象，如 ``{"error", "missing"}``；
    请求体校验失败时是 FastAPI 的错误列表）；``code`` 是稳定的机器可读错误码，见 ``speclock_core.errors``。"""

    detail: Any
    code: str


# 所有需要 key 的接口都可能返回的错误（挂在路由上让接口文档里看得到）
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorOut, "description": desc}
    for code, desc in (
        (400, "请求本身不合法"),
        (401, "缺少或不认识的 X-API-Key"),
        (403, "权限不足 / 不是你的资源"),
        (404, "不存在，或无权访问"),
        (409, "与当前状态冲突"),
        (422, "请求内容校验失败"),
    )
}


class DeletedOut(Out):
    id: int
    deleted: bool


class HealthOut(Out):
    status: Literal["ok", "error"]
    version: str


class WebSessionOut(Out):
    key: str  # 绑定了 project_id 的只读 key：网页用它画界面，所以只看得到这一个项目
    project_id: int


class WebProjectOut(Out):
    id: int
    name: str


class MeOut(Out):
    key_id: int
    hint: str
    kind: str  # human | agent
    label: str
    project_id: int | None
    role: str | None
    permissions: list[str]


class ProjectOut(Out):
    id: int
    name: str


class ProjectDeletedOut(Out):
    id: int
    deleted: bool
    deleted_keys: int


# ---------- 审核单 / Commit ----------

CRStatus = Literal["draft", "pending_review", "approved", "applied", "rejected", "superseded"]


class ItemOut(Out):
    """验收条件 / 规则条目。"""

    id: str
    name: str
    detail: str


class CoverageOut(Out):
    covered: list[str]
    missing: list[str]


class CommitOut(Out):
    id: int
    seq: int
    covers: list[str]
    change_note: str
    ops: list[dict[str, Any]]
    result: dict[str, Any]
    created_by: str
    created_at: datetime


class CRSummaryOut(Out):
    id: int
    project_id: int
    title: str
    intent: str
    expected_outcome: str
    obsolete: list[str]
    acceptance: list[ItemOut]
    impact_note: str
    kind: Literal["business", "internal"]
    kind_reason: str
    status: CRStatus
    content_hash: str  # 提交（pending_review）起才有，草稿时是空串
    supersedes_id: int | None
    superseded_by_id: int | None
    created_by: str
    created_at: datetime
    submitted_at: datetime | None
    decided_by: str
    decided_at: datetime | None
    decision_via: str  # "" | cli | natural_language | api | agent_declared
    decision_evidence: str
    decision_note: str
    applied_at: datetime | None
    commit_count: int
    coverage: CoverageOut


class CROut(CRSummaryOut):
    """审核单详情 = 摘要 + 它名下的 Commit。"""

    commits: list[CommitOut]


class CommitCreatedBlock(Out):
    block_id: int
    title: str
    capability_id: int
    version: str
    level: str
    created: bool
    delta: Delta


class CommitCapabilityVersion(Out):
    capability_id: int
    version: str
    level: str


class CommitDryRunOut(Out):
    """``dryRun=true``：完整执行后回滚，不落库。"""

    dry_run: Literal[True]
    cr_id: int
    created: dict[str, dict[str, Any]]  # ref 名 -> {type, id}
    blocks: list[CommitCreatedBlock]
    archived_blocks: list[int]
    restored_blocks: list[int]
    moved_blocks: list[int]
    capability_versions: list[CommitCapabilityVersion]


class CommitAppliedOut(Out):
    dry_run: Literal[False]
    cr_id: int
    commit_id: int
    seq: int
    covers: list[str]
    created: dict[str, dict[str, Any]]
    blocks: list[CommitCreatedBlock]
    archived_blocks: list[int]
    restored_blocks: list[int]
    moved_blocks: list[int]
    capability_versions: list[CommitCapabilityVersion]


# ---------- 执行记录 ----------

WorkStatus = Literal["pending", "in_progress", "blocked", "failed", "implemented", "verified", "superseded"]


class WorkSummaryOut(Out):
    id: int
    block_id: int
    block_title: str
    capability_id: int
    capability_title: str
    business: str
    version: str
    status: WorkStatus
    claimed_by: str
    reason: str
    created_at: datetime
    updated_at: datetime


class WorkEventOut(Out):
    event: str
    from_: str | None = Field(alias="from")
    to: str
    actor: str
    note: str
    detail: dict[str, Any]
    created_at: datetime


class WorkDetailOut(WorkSummaryOut):
    """领取 / 查看一条记录：摘要 + 逐条验收结果 + 事件历史 + 锁定到该版本的完整规格。"""

    implementation: list[dict[str, Any]]
    verification: list[dict[str, Any]]
    events: list[WorkEventOut]
    spec: BlockOut


# ---------- 规格读视图 ----------


class VersionEventOut(Out):
    event: str
    from_: str | None = Field(alias="from")
    to: str
    actor: str
    note: str
    created_at: datetime


class BlockHistoryEntry(Out):
    """``/blocks/{id}/history``：agent 看的版本历史（不含执行进展）。"""

    version: str
    level: str
    status: Literal["current", "deprecated"]
    superseded_by: str | None
    change_note: str
    delta: dict[str, Any]
    cr_id: int | None
    commit_id: int | None
    published_by: str
    published_at: datetime | None


class BlockVersionEntry(BlockHistoryEntry):
    """``/blocks/{id}/versions``：人看的版本列表，多了执行记录与事件。"""

    work_id: int | None
    execution_status: str | None
    events: list[VersionEventOut]


class BlockVersionFull(Out):
    """``/blocks/{id}/versions/{version}``：单个版本的完整快照（不限模块状态）。"""

    block_id: int
    title: str
    status: str  # 模块状态：draft | published | archived
    version: str
    content_md: str
    rules: list[dict[str, Any]]
    acceptance: list[dict[str, Any]]
    apis: list[dict[str, Any]]
    openapi_yaml: str
    level: str
    change_note: str
    delta: dict[str, Any]
    cr_id: int | None
    commit_id: int | None
    published_by: str
    published_at: datetime | None
    work_id: int | None
    execution_status: str | None


class CapabilityVersionEntry(Out):
    """``/capabilities/{id}/history`` 与 ``/capabilities/{id}/versions`` 共用。"""

    version: str
    status: Literal["current", "deprecated"]
    superseded_by: str | None
    manifest: dict[str, Any]  # 模块 id -> {title, version}
    triggered_by_block_id: int | None
    change_note: str
    cr_id: int | None
    commit_id: int | None
    published_by: str
    published_at: datetime | None


class DiffOut(Out):
    block_id: int
    from_: str = Field(alias="from")
    to: str
    content_diff: str
    openapi_diff: str
    delta: Delta
    level: str


class DiffUnavailableOut(Out):
    """模块只有一个已发布版本时的友好提示（200，不是错误）。"""

    block_id: int
    message: str
    versions: list[str]


# ---------- 管理读视图 ----------


class TreeBlock(Out):
    id: int
    title: str
    status: str
    current_published_version: str | None
    current_published_at: datetime | None
    execution_status: str | None


class TreeCapability(Out):
    id: int
    title: str
    summary: str
    current_version: str | None
    blocks: list[TreeBlock]


class TreeBusiness(Out):
    id: int
    name: str
    capabilities: list[TreeCapability]


class TreeProject(Out):
    id: int
    name: str
    businesses: list[TreeBusiness]


class ArchivedBlockOut(Out):
    id: int
    title: str
    current_published_version: str | None
    archived_at: datetime | None
    capability_id: int
    capability_title: str
    business_id: int
    business_name: str
    project_id: int
    project_name: str


class ActivityOut(Out):
    id: int
    actor: str
    action: str
    target: str
    detail: dict[str, Any]
    created_at: datetime


# ---------- 搜索 ----------


class BlockHit(Out):
    block_id: int
    block_title: str
    version: str | None
    capability_id: int
    capability_title: str
    business: str
    project_id: int
    type: Literal["module", "rule", "acceptance", "api"]
    field: str
    item_id: str
    title: str
    snippet: str


class CrHit(Out):
    type: Literal["cr"]
    cr_id: int
    status: CRStatus
    kind: Literal["business", "internal"]
    project_id: int
    field: str
    item_id: str
    title: str
    snippet: str


class SearchOut(Out):
    query: str
    total: int
    truncated: bool
    hits: list[BlockHit | CrHit]


# ---------- 密钥与角色 ----------


class KeyBase(Out):
    id: int
    hint: str
    prefix: str  # human | agent
    role: str | None
    label: str
    key_file: str
    project_id: int | None
    created_at: datetime


class KeyListEntry(KeyBase):
    last_active_at: datetime | None
    actions_7d: int
    reads_7d: int


class KeyCreatedOut(KeyBase):
    """创建密钥。Agent 类 key 写进 ``.speclock/keys/``：带 ``mcp_config``、不带明文 ``key``；
    人类 key（或没有 ``.speclock/`` 时）带明文 ``key``（仅此一次）、不带 ``mcp_config``。
    不出现的字段整个键都不在响应里。"""

    key: str | None = None
    notice: str
    mcp_config: dict[str, Any] | None = None


class RoleOut(Out):
    id: int
    name: str
    kind: str
    description: str
    permissions: list[str]
    builtin: bool
    key_count: int


class PermissionOut(Out):
    name: str
    description: str
    human_only: bool
