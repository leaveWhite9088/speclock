"""SQLAlchemy models — mirrors MVP requirements doc section 9.

Hierarchy: Project -> Domain (大业务) -> Document (业务文档) -> Block (块).
A Block always carries a mutable working draft (content_md / openapi_yaml /
nfr_md); publishing snapshots the draft into an immutable BlockVersion.
Agents can only ever read BlockVersion rows, never the draft fields.
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
    """业务文档 (e.g. 经营日报) — a named group of blocks."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"))
    title: Mapped[str]
    doc_type: Mapped[str] = mapped_column(default="business")  # business|requirement|meeting

    domain: Mapped[Domain] = relationship(back_populates="documents")
    blocks: Mapped[list["Block"]] = relationship(back_populates="document")


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    title: Mapped[str]
    summary: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="draft")  # draft|published|archived
    current_published_version: Mapped[str | None] = mapped_column(nullable=True)

    # working draft — writable by humans only, never exposed to agents
    draft_content_md: Mapped[str] = mapped_column(Text, default="")
    draft_openapi_yaml: Mapped[str] = mapped_column(Text, default="")
    draft_nfr_md: Mapped[str] = mapped_column(Text, default="")

    document: Mapped[Document] = relationship(back_populates="blocks")
    versions: Mapped[list["BlockVersion"]] = relationship(
        back_populates="block", order_by="BlockVersion.id"
    )


class BlockVersion(Base):
    """Immutable published snapshot."""

    __tablename__ = "block_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    version: Mapped[str]  # semver MAJOR.MINOR.PATCH
    content_md: Mapped[str] = mapped_column(Text, default="")
    openapi_yaml: Mapped[str] = mapped_column(Text, default="")
    nfr_md: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    delta_json: Mapped[str] = mapped_column(Text, default="{}")  # {added, modified, removed}
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)

    block: Mapped[Block] = relationship(back_populates="versions")


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
    proposed_openapi_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)
    prefix: Mapped[str]  # human|agent
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    label: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]  # api key or 'human:...' / 'agent:...'
    action: Mapped[str]  # publish|pull|proposal_submit|proposal_resolve|ack|...
    target: Mapped[str]  # e.g. block:3@1.2.0
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
