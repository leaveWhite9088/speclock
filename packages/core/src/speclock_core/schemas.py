"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------- structured API entries (编辑与 diff 的真相源) ----------



class StrictModel(BaseModel):
    """请求体：不认识的字段直接 422，而不是悄悄忽略——拼错字段名、或者客户端比服务端新
    （发了服务端还不认识的字段）时，调用方能立刻发现，而不是误以为生效了。"""

    model_config = ConfigDict(extra="forbid")


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


class ItemEntry(BaseModel):
    """带稳定 id 的条目（业务规则 / 验收条件同构）：名称 + 详述。
    id 形如 R-1 / AC-1，创建时缺省由服务端分配，之后不变、编号不复用。"""

    id: str | None = None
    name: str
    detail: str


RuleEntry = ItemEntry
AcceptanceEntry = ItemEntry


# ---------- 管理：项目 / 密钥 / 角色 ----------


class RenameRequest(BaseModel):
    name: str


class ProjectCreate(BaseModel):
    name: str


class KeyCreate(StrictModel):
    role: str  # 角色名（见 GET /roles）；key 的类别（human / agent）由角色的 kind 决定
    label: str = ""
    # 项目隔离：绑定项目后该 key 只能访问该项目的内容；None = 全局。
    project_id: int | None = None
    # 创建来源与依据：Agent 代人创建须 via=natural_language 并附人的原话
    via: str = Field(default="api", pattern="^(cli|natural_language|api)$")
    evidence: str = ""


class RoleCreate(BaseModel):
    name: str
    kind: str = Field(pattern="^(human|agent)$")
    description: str = ""
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None


# ---------- 审核单（Change Request）与 Commit ----------


class CRCreate(StrictModel):
    """新建审核单（草稿，可以先不完整；提交时才校验完备性）。"""

    project_id: int | None = None  # 项目绑定的 key 可省略
    title: str
    intent: str = ""  # 为什么变
    expected_outcome: str = ""  # 变成什么样
    obsolete: list[str] = []  # 哪些旧认知不再成立
    acceptance: list[ItemEntry] = []  # 验收条件（id 形如 AC-n，缺省由服务端分配）
    impact_note: str = ""  # 影响说明（需求 Agent 写给人看）
    supersedes_id: int | None = None  # 取代一个已批准但未完成的审核单
    # business（默认，须人批准）| internal（内部整理，须有 cr.internal 权限，提交即生效）
    kind: str = Field(default="business", pattern="^(business|internal)$")
    kind_reason: str = ""  # internal 必填：为什么这不算业务变更


class CRUpdate(StrictModel):
    """编辑草稿审核单：只传要改的字段；acceptance 是整体替换（带 id 的条目保留 id）。"""

    title: str | None = None
    intent: str | None = None
    expected_outcome: str | None = None
    obsolete: list[str] | None = None
    acceptance: list[ItemEntry] | None = None
    impact_note: str | None = None
    supersedes_id: int | None = None
    kind: str | None = Field(default=None, pattern="^(business|internal)$")
    kind_reason: str | None = None


class CRApprove(StrictModel):
    content_hash: str  # 批准的就是人看到的那一版：必须与审核单当前内容哈希一致
    via: str = Field(default="api", pattern="^(cli|natural_language|api)$")
    evidence: str = ""  # via=natural_language 时必填：人的原话
    note: str = ""


class CRReject(StrictModel):
    reason: str  # 驳回理由（必填）：需求 Agent 据此另开新审核单
    via: str = Field(default="api", pattern="^(cli|natural_language|api)$")
    evidence: str = ""


class CommitCreate(StrictModel):
    ops: list[dict]  # 见 commits.py 顶部的 op 清单
    covers: list[str] = []  # 本 Commit 满足审核单的哪些验收条件（AC-n）
    change_note: str = ""
    dryRun: bool = False  # 预览：完整执行后回滚，返回会得到的版本 / 级别标签 / delta


class AcResult(StrictModel):
    """对一条验收条件的结果：实现方自测 / 验证方独立验收都用它。"""

    ac_id: str
    result: str = Field(pattern="^(pass|fail)$")
    evidence: str  # 证据：测试输出、接口返回、观察到的现象等（必填）


class WorkResults(StrictModel):
    results: list[AcResult]
    note: str = ""


class WorkReason(StrictModel):
    reason: str


class ApiOp(BaseModel):
    """api_ops 的一条变更：按 api 字段（方法 + 路径）定位目标条目。"""

    op: str = Field(pattern="^(upsert|delete)$")
    api: str  # 定位键，如 "GET /api/daily-report"
    entry: ApiEntry | None = None  # upsert 必填，delete 必须为 null


class ItemOp(BaseModel):
    """rule_ops / acceptance_ops 的一条变更：按稳定 id 定位目标条目。
    - upsert + id：修改该条（id 不存在 → 409）；
    - upsert 不带 id：新增一条（id 由服务端分配）；
    - delete + id：删除该条。"""

    op: str = Field(pattern="^(upsert|delete)$")
    id: str | None = None
    entry: ItemEntry | None = None  # upsert 必填，delete 必须为 null


RuleOp = ItemOp
AcceptanceOp = ItemOp


# ---------- responses ----------


class IndexBlock(BaseModel):
    block_id: int
    title: str
    version: str
    summary: str  # <= 50 chars
    work_id: int | None = None  # 当前版本的执行记录 id
    execution_status: str | None = None  # 当前版本的执行状态（见 executions.py）


class IndexCapability(BaseModel):
    capability_id: int
    title: str
    summary: str = ""
    version: str | None  # 当前小业务版本
    blocks: list[IndexBlock]


class IndexBusiness(BaseModel):
    business: str
    capabilities: list[IndexCapability]


class Delta(BaseModel):
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    # 规则 / 验收条件 delta（按稳定 id 匹配；modified = 详述变了，renamed = 只改了名称）
    rules_added: list[str] = []
    rules_removed: list[str] = []
    rules_modified: list[str] = []
    rules_renamed: list[str] = []
    acceptance_added: list[str] = []
    acceptance_removed: list[str] = []
    acceptance_modified: list[str] = []
    acceptance_renamed: list[str] = []


class BlockOut(BaseModel):
    block_id: int
    title: str
    version: str
    content_md: str
    rules: list[dict]  # 结构化业务规则清单 [{id, name, detail}]
    acceptance: list[dict]  # 结构化验收条件清单 [{id, name, detail}]
    apis: list[dict]  # 结构化 API 列表（真相源，条目带 desc 端点语义）
    openapi_yaml: str  # 发布时生成的 OpenAPI 3.x（机器消费）
    change_note: str
    # 机械算出的版本级别标签（initial|major|minor|patch），仅供参考
    level: str = ""
    # 派生状态：current = 最新未作废版本；deprecated = 已被更新版本取代
    status: str = "current"
    superseded_by: str | None = None
    delta: Delta
    published_at: datetime | None
    work_id: int | None = None  # 该版本的执行记录 id
    execution_status: str | None = None  # 该版本的执行状态
    # 溯源：产生这个版本的审核单与 Commit（灌入的示例数据为空）
    cr_id: int | None = None
    commit_id: int | None = None


class PublishResult(BaseModel):
    block_id: int
    version: str
    capability_id: int
    capability_version: str  # 本次发布派生的小业务版本（dryRun 时为预测值；Commit 内为空，由 Commit 统一派生）
    delta: Delta
    level: str = ""  # 机械算出的版本级别标签（initial|major|minor|patch）
    groups: list[dict] = []  # 按 API 分组的结构化 delta（预览 / diff 页用）


class CapabilityIndexEntry(BaseModel):
    capability_id: int
    title: str
    summary: str = ""
    business: str
    version: str  # 当前小业务版本


class CapabilityOut(BaseModel):
    capability_id: int
    title: str
    summary: str = ""
    version: str
    manifest: list[dict]  # [{block_id, title, version}]
    published_at: datetime | None
