"""SQLAlchemy models — mirrors MVP requirements doc section 9, revised:

- 块（Block）就是模块，必须挂在 Capability（小业务）下；Capability 只做聚合与
  版本快照，不自带 API / 规则（它们都属于 Block）。
- 每个模块的内容：业务描述（背景叙述 content_md + 结构化规则清单 rules_json）
  + API 列表（结构化 apis_json，
  编辑与 diff 的真相源）+ 验收条件（结构化 acceptance_json）；规则与验收条件的
  每一条带稳定 id（R-n / AC-n，编号不复用）；openapi_yaml 是发布时
  从 apis_json 生成的机器消费产物。
- 两级版本：模块独立 semver 发布；任何模块发布成功时所属小业务派生一个
  CapabilityVersion（manifest = 该小业务全部模块当前已发布版本清单）。
- 写入只有一条路：审核单（ChangeRequest）经人批准后，由需求 Agent 提交 Commit。
  BlockVersion / CapabilityVersion 记录产生它的 cr_id / commit_id，可溯源。
- 权限：key → Role → 权限集合（见 permissions.py）。

Hierarchy: Project -> Business (大业务) -> Capability (小业务) -> Block (模块).
Agents can only ever read BlockVersion / CapabilityVersion rows, never drafts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speclock.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    businesses: Mapped[list["Business"]] = relationship(back_populates="project")


class Business(Base):
    """大业务 (top-level business area, e.g. 运营 / 采购 / 商品)."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str]

    project: Mapped[Project] = relationship(back_populates="businesses")
    capabilities: Mapped[list["Capability"]] = relationship(back_populates="business")


class Capability(Base):
    """小业务 (e.g. 经营日报) — 一组模块（Block）组成的完整业务。自身只做聚合与
    版本控制：版本 = 其全部模块当前版本的确定快照（见 CapabilityVersion）。"""

    __tablename__ = "capabilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    title: Mapped[str]
    summary: Mapped[str] = mapped_column(default="")  # 一句话简述，随索引下发给 agent
    current_version: Mapped[str | None] = mapped_column(nullable=True)  # 小业务级 semver

    business: Mapped[Business] = relationship(back_populates="capabilities")
    blocks: Mapped[list["Block"]] = relationship(back_populates="capability")
    versions: Mapped[list["CapabilityVersion"]] = relationship(
        back_populates="capability", order_by="CapabilityVersion.id"
    )


class Block(Base):
    """模块：业务描述（背景叙述 + 结构化规则清单 + 边界与异常）
    + API 列表 + 非功能性需求。"""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("capabilities.id"))
    title: Mapped[str]
    summary: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="draft")  # draft|published|archived
    current_published_version: Mapped[str | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)  # 最近归档时间

    # working draft — writable by humans only, never exposed to agents
    draft_content_md: Mapped[str] = mapped_column(Text, default="")  # 业务背景与流程叙述
    draft_rules_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化业务规则清单
    draft_apis_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化 API 列表
    draft_acceptance_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化验收条件清单

    capability: Mapped[Capability] = relationship(back_populates="blocks")
    versions: Mapped[list["BlockVersion"]] = relationship(
        back_populates="block", order_by="BlockVersion.id"
    )


class BlockVersion(Base):
    """Immutable published module snapshot."""

    __tablename__ = "block_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    version: Mapped[str]  # semver MAJOR.MINOR.PATCH
    content_md: Mapped[str] = mapped_column(Text, default="")  # 业务背景与流程叙述
    rules_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化业务规则清单
    apis_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化 API 列表（真相源）
    openapi_yaml: Mapped[str] = mapped_column(Text, default="")  # 发布时生成的 OpenAPI 3.x
    acceptance_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化验收条件清单
    # 版本级别标签 initial|major|minor|patch：发布时由 diffing.bump_level 机械算出，
    # 仅供外部 Agent 参考，Core 不据此强制任何行为
    level: Mapped[str] = mapped_column(default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    delta_json: Mapped[str] = mapped_column(Text, default="{}")  # {added, modified, removed}
    # 溯源：这个版本由哪个审核单的哪个 Commit 产生（seed / inject 灌入的数据为空）
    cr_id: Mapped[int | None] = mapped_column(ForeignKey("change_requests.id"), nullable=True)
    commit_id: Mapped[int | None] = mapped_column(ForeignKey("commits.id"), nullable=True)
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)

    block: Mapped[Block] = relationship(back_populates="versions")


class CapabilityVersion(Base):
    """文档级版本：任一模块发布成功时派生的 manifest 快照。"""

    __tablename__ = "capability_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("capabilities.id"))
    version: Mapped[str]  # semver，派生规则见 diffing.derive_capability_version
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")  # {block_id: {title, version}}
    triggered_by_block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    change_note: Mapped[str] = mapped_column(Text, default="")
    cr_id: Mapped[int | None] = mapped_column(ForeignKey("change_requests.id"), nullable=True)
    commit_id: Mapped[int | None] = mapped_column(ForeignKey("commits.id"), nullable=True)
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)

    capability: Mapped[Capability] = relationship(back_populates="versions")


class ChangeRequest(Base):
    """审核单（CR）：人与需求 Agent 之间的核心对象，只含业务意图——为什么变、变成
    什么样、哪些旧认知不再成立、验收条件。不含「改哪个 Block / 谁来改 / 什么技术」。

    状态：draft → pending_review → approved → applied；pending_review → rejected；
    approved → superseded。提交（pending_review）起内容冻结，批准后不可改。
    """

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str]
    intent: Mapped[str] = mapped_column(Text, default="")  # 为什么变
    expected_outcome: Mapped[str] = mapped_column(Text, default="")  # 变成什么样
    obsolete_json: Mapped[str] = mapped_column(Text, default="[]")  # 不再成立的旧认知 [str]
    acceptance_json: Mapped[str] = mapped_column(Text, default="[]")  # [{id, name, detail}]，AC-n
    impact_note: Mapped[str] = mapped_column(Text, default="")  # 需求 Agent 写给人看的影响说明
    # 类型：business（业务变更，须人批准）| internal（内部整理，不改变业务内容，由需求 Agent
    # 自行判定、提交即生效；Core 在 Commit 时机械检查规则 / 验收条件 / API 的条目总和不变）
    kind: Mapped[str] = mapped_column(default="business")
    kind_reason: Mapped[str] = mapped_column(Text, default="")  # internal 必填：为什么不算业务变更
    status: Mapped[str] = mapped_column(default="draft")
    content_hash: Mapped[str] = mapped_column(default="")  # 提交时冻结内容的哈希；批准须带上
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("change_requests.id"), nullable=True
    )
    superseded_by_id: Mapped[int | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(default="")  # key hint
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # 人的决定（批准 / 驳回）：谁、经由什么渠道、凭什么（自然语言批准留原话）
    decided_by: Mapped[str] = mapped_column(default="")
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_via: Mapped[str] = mapped_column(default="")  # cli|natural_language|api|agent_declared
    decision_evidence: Mapped[str] = mapped_column(Text, default="")
    decision_note: Mapped[str] = mapped_column(Text, default="")  # 驳回理由 / 批准备注
    applied_at: Mapped[datetime | None] = mapped_column(nullable=True)

    commits: Mapped[list["Commit"]] = relationship(
        back_populates="change_request", order_by="Commit.id"
    )


class Commit(Base):
    """已批准审核单下的一次原子写入：一组 ops，应用即发布，可涉及多个 Block /
    Capability。声明自己满足审核单的哪些验收条件（covers），供覆盖检查与溯源。"""

    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(primary_key=True)
    cr_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"))
    seq: Mapped[int]  # 审核单内序号，从 1 起
    ops_json: Mapped[str] = mapped_column(Text, default="[]")
    covers_json: Mapped[str] = mapped_column(Text, default="[]")  # [AC-n]
    change_note: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")  # 落地结果：版本 / 新建对象
    created_by: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    change_request: Mapped[ChangeRequest] = relationship(back_populates="commits")


class ExecutionRecord(Base):
    """执行记录：「把模块 X 的 v 版本实现出来」这件事的状态。每个已发布版本一条（自动产生），
    规格状态与执行状态分开存放。

    状态：pending → in_progress → implemented → verified；in_progress 可到 blocked /
    failed（failed、blocked 可重新领取）；验收不通过回到 failed；模块发布新版本时
    未结束的记录变 superseded。每次转换写一条 ExecutionEvent。
    """

    __tablename__ = "execution_records"
    __table_args__ = (UniqueConstraint("block_id", "version", name="uq_exec_block_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    version: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    claimed_by: Mapped[str] = mapped_column(default="")  # key hint；空 = 无人持有
    claimed_by_key_id: Mapped[int | None] = mapped_column(nullable=True)
    implemented_by_key_id: Mapped[int | None] = mapped_column(nullable=True)  # 验证者须不同于它
    reason: Mapped[str] = mapped_column(Text, default="")  # 最近一次 blocked / failed 的原因
    results_json: Mapped[str] = mapped_column(Text, default="[]")  # 实现方逐条验收条件的结果
    verification_json: Mapped[str] = mapped_column(Text, default="[]")  # 验证方逐条结果
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    block: Mapped[Block] = relationship()
    events: Mapped[list["ExecutionEvent"]] = relationship(
        back_populates="record", order_by="ExecutionEvent.id"
    )


class ExecutionEvent(Base):
    """执行记录的状态转换历史（只追加）。"""

    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("execution_records.id"))
    event: Mapped[str]  # created|claim|release|blocked|failed|implemented|verified|verify_failed|superseded
    from_status: Mapped[str] = mapped_column(default="")
    to_status: Mapped[str]
    actor: Mapped[str] = mapped_column(default="")
    note: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    record: Mapped[ExecutionRecord] = relationship(back_populates="events")


class Role(Base):
    """角色 = 权限集合（权限目录见 permissions.py）。kind 决定绑定它的 key 的类别。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str]  # human|agent
    description: Mapped[str] = mapped_column(default="")
    permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    builtin: Mapped[bool] = mapped_column(default=False)  # 预置角色：可改权限，不可删


class ApiKey(Base):
    """密钥只存 SHA-256 哈希（key 列）与展示用 hint；明文仅在创建时返回一次。"""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)  # 明文的 SHA-256 hex
    hint: Mapped[str] = mapped_column(default="")  # 展示用，如 human-…1a2b
    prefix: Mapped[str]  # human|agent，与角色的 kind 一致
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    label: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    role: Mapped[Role | None] = relationship()


class MigrationMark(Base):
    """一次性数据迁移的完成标记（如给预置角色补新权限），保证每项只做一次。"""

    __tablename__ = "migration_marks"

    name: Mapped[str] = mapped_column(primary_key=True)
    done_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]  # api key
    action: Mapped[str]  # publish|pull|proposal_submit|proposal_resolve|ack|...
    target: Mapped[str]  # e.g. block:3@1.2.0
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
