"""SQLAlchemy models — mirrors MVP requirements doc section 9, revised:

- 块（Block）就是模块（小业务），必须挂在 Document（业务文档）下。
- 每个模块的内容：业务描述（背景叙述 content_md + 结构化规则清单 rules_json
  + 边界与异常 edge_md）+ API 列表（结构化 apis_json，
  编辑与 diff 的真相源）+ 非功能性需求（Markdown）；openapi_yaml 是发布时
  从 apis_json 生成的机器消费产物。
- 两级版本：模块独立 semver 发布；任何模块发布成功时所属文档派生一个
  DocumentVersion（manifest = 该文档全部模块当前已发布版本清单）。

Hierarchy: Project -> Domain (大业务) -> Document (业务文档) -> Block (模块).
Agents can only ever read BlockVersion / DocumentVersion rows, never drafts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speclock.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    domains: Mapped[list["Domain"]] = relationship(back_populates="project")


class Domain(Base):
    """大业务 (top-level business area, e.g. 运营 / 采购 / 商品)."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str]

    project: Mapped[Project] = relationship(back_populates="domains")
    documents: Mapped[list["Document"]] = relationship(back_populates="domain")


class Document(Base):
    """业务文档 (e.g. 经营日报) — a named group of modules (blocks)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    title: Mapped[str]
    doc_type: Mapped[str] = mapped_column(default="business")  # business|requirement|meeting
    current_version: Mapped[str | None] = mapped_column(nullable=True)  # 文档级 semver

    domain: Mapped[Domain] = relationship(back_populates="documents")
    blocks: Mapped[list["Block"]] = relationship(back_populates="document")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", order_by="DocumentVersion.id"
    )


class Block(Base):
    """模块（小业务）：业务描述（背景叙述 + 结构化规则清单 + 边界与异常）
    + API 列表 + 非功能性需求。"""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    title: Mapped[str]
    summary: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="draft")  # draft|published|archived
    current_published_version: Mapped[str | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)  # 最近归档时间

    # 完成标记：「当前已发布版本已被实现完成」。发布新版本时 completed 自动重置
    # 为 False；completed_version 保留为「上次完成对应的版本号」（历史信息）。
    completed: Mapped[bool] = mapped_column(default=False)
    completed_version: Mapped[str | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # working draft — writable by humans only, never exposed to agents
    draft_content_md: Mapped[str] = mapped_column(Text, default="")  # 业务背景与流程叙述
    draft_rules_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化业务规则清单
    draft_edge_md: Mapped[str] = mapped_column(Text, default="")  # 边界与异常（可选）
    draft_apis_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化 API 列表
    draft_nfr_md: Mapped[str] = mapped_column(Text, default="")

    document: Mapped[Document] = relationship(back_populates="blocks")
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
    edge_md: Mapped[str] = mapped_column(Text, default="")  # 边界与异常（可选）
    apis_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化 API 列表（真相源）
    openapi_yaml: Mapped[str] = mapped_column(Text, default="")  # 发布时生成的 OpenAPI 3.x
    nfr_md: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    delta_json: Mapped[str] = mapped_column(Text, default="{}")  # {added, modified, removed}
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)

    block: Mapped[Block] = relationship(back_populates="versions")


class DocumentVersion(Base):
    """文档级版本：任一模块发布成功时派生的 manifest 快照。"""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    version: Mapped[str]  # semver，派生规则见 diffing.derive_document_version
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")  # {block_id: {title, version}}
    triggered_by_block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    change_note: Mapped[str] = mapped_column(Text, default="")
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)

    document: Mapped[Document] = relationship(back_populates="versions")


class Proposal(Base):
    """The only write channel available to agents."""

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    author_type: Mapped[str] = mapped_column(default="agent")  # agent|human
    description: Mapped[str] = mapped_column(Text)  # 问题描述
    suggestion: Mapped[str] = mapped_column(Text)  # 建议改法
    scenario: Mapped[str] = mapped_column(Text, default="")  # 发现场景 / 代码位置
    proposed_content_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_apis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(default="submitted")  # submitted|published|rejected
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    published_version: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Ack(Base):
    """Agent receipt: 'implemented against block X @ version Y'."""

    __tablename__ = "acks"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    version: Mapped[str]
    agent_key: Mapped[str]
    task_desc: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApiKey(Base):
    """密钥只存 SHA-256 哈希（key 列）与展示用 hint；明文仅在创建时返回一次。"""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)  # 明文的 SHA-256 hex
    hint: Mapped[str] = mapped_column(default="")  # 展示用，如 human-…1a2b
    prefix: Mapped[str]  # human|agent
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    label: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]  # api key
    action: Mapped[str]  # publish|pull|proposal_submit|proposal_resolve|ack|...
    target: Mapped[str]  # e.g. block:3@1.2.0
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
