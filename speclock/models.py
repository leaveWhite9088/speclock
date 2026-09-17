"""SQLAlchemy models — mirrors MVP requirements doc section 9, revised:

- 块（Block）就是模块（小业务），必须挂在 Document（业务文档）下。
- 每个模块的内容：业务描述（背景叙述 content_md + 结构化规则清单 rules_json）
  + API 列表（结构化 apis_json，
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
    apis_json: Mapped[str] = mapped_column(Text, default="[]")  # 结构化 API 列表（真相源）
    openapi_yaml: Mapped[str] = mapped_column(Text, default="")  # 发布时生成的 OpenAPI 3.x
    nfr_md: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    delta_json: Mapped[str] = mapped_column(Text, default="{}")  # {added, modified, removed}
    published_by: Mapped[str] = mapped_column(default="")
    published_at: Mapped[datetime] = mapped_column(default=utcnow)
    # 版本作废（逻辑删除）：非空即作废——对 agent 与页面均不可见，行保留在库中
    voided_at: Mapped[datetime | None] = mapped_column(nullable=True)

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


# ---------- 会议记录（独立于 Project→Domain→Document→Block 链路） ----------


class MeetingSeries(Base):
    """业务线（如"采购部分"）：一组同业务线会议的容器。"""

    __tablename__ = "meeting_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str]
    share_token: Mapped[str | None] = mapped_column(
        unique=True, index=True, nullable=True
    )  # "ms-"+token_hex(16)，明文存；存量行由 db 迁移回填
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    meetings: Mapped[list["Meeting"]] = relationship(back_populates="series")
    docs: Mapped[list["SeriesDoc"]] = relationship(back_populates="series")


class Meeting(Base):
    """一次会议：按目录名导入的一批 md 文件 + 哈希码分享配置。"""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("meeting_series.id"))
    name: Mapped[str]  # 如"采购第5次业务交流"
    date: Mapped[str | None] = mapped_column(nullable=True)  # 从目录名 YYMMDD- 前缀解析，ISO 日期
    dir_name: Mapped[str] = mapped_column(default="")  # 原始目录名
    share_token: Mapped[str] = mapped_column(unique=True, index=True)  # "mt-"+token_hex(16)，明文存
    share_kinds_json: Mapped[str] = mapped_column(Text, default='["requirements", "facts", "confirm"]')
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    series: Mapped[MeetingSeries] = relationship(back_populates="meetings")
    files: Mapped[list["MeetingFile"]] = relationship(back_populates="meeting")


class MeetingFile(Base):
    """会议下的一份 md 文件。切块文件（精准需求/业务事实）的真相源是 chunks，
    content_md 为渲染产物；其余文件整篇存/整篇编辑。"""

    __tablename__ = "meeting_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    filename: Mapped[str]  # 原始文件名
    kind: Mapped[str]  # transcript|requirements|facts|confirm|questions|glossary|other
    current_version: Mapped[str] = mapped_column(default="1.0.0")  # 文件级 semver
    content_md: Mapped[str] = mapped_column(Text, default="")  # 当前内容（v1=上传原文）
    parse_status: Mapped[str] = mapped_column(default="na")  # ok|degraded|failed|na
    parse_error: Mapped[str] = mapped_column(Text, default="")  # 可直接贴给 agent 的报错
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="files")
    versions: Mapped[list["MeetingFileVersion"]] = relationship(
        back_populates="file", order_by="MeetingFileVersion.id"
    )
    chunks: Mapped[list["MeetingChunk"]] = relationship(
        back_populates="file", order_by="MeetingChunk.seq"
    )


class MeetingFileVersion(Base):
    """文件版本快照：v1 存上传原文，之后每次编辑一个不可变快照。"""

    __tablename__ = "meeting_file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("meeting_files.id"))
    version: Mapped[str]  # semver MAJOR.MINOR.PATCH
    content_md: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(default="upload")  # upload|edit
    bump: Mapped[str] = mapped_column(default="none")  # major|minor|patch|none
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(default="")  # key hint
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    file: Mapped[MeetingFile] = relationship(back_populates="versions")


class MeetingChunk(Base):
    """切块文件的单个块：条目（REQ/FACT/CON/ACT/Q）或散文节（prose，
    含标题行、会议概括、覆盖校验等，保持 seq 顺序以完整渲染回文件）。"""

    __tablename__ = "meeting_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("meeting_files.id"))
    seq: Mapped[int]
    section: Mapped[str] = mapped_column(default="")  # 所属 ## / ### 标题
    ref_id: Mapped[str | None] = mapped_column(nullable=True)  # REQ-01/FACT-03/...；prose 为 None
    chunk_type: Mapped[str]  # req|fact|con|act|q|prose
    fields_json: Mapped[str] = mapped_column(Text, default="{}")  # statement/status/.../quotes[]
    text_md: Mapped[str] = mapped_column(Text, default="")  # 该块渲染文本，供搜索

    file: Mapped[MeetingFile] = relationship(back_populates="chunks")


# ---------- 业务线汇总文档（总精准需求 / 总业务事实） ----------


class SeriesDoc(Base):
    """业务线下的汇总文档：每个业务线每类一份（requirements|facts），
    由 refresh 从各会议文件汇总生成，之后可块级编辑（联动源文件）。"""

    __tablename__ = "series_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("meeting_series.id"))
    kind: Mapped[str]  # requirements|facts
    current_version: Mapped[str] = mapped_column(default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    series: Mapped[MeetingSeries] = relationship(back_populates="docs")
    items: Mapped[list["SeriesItem"]] = relationship(
        back_populates="doc", order_by="SeriesItem.seq"
    )
    versions: Mapped[list["SeriesDocVersion"]] = relationship(
        back_populates="doc", order_by="SeriesDocVersion.id"
    )


class SeriesItem(Base):
    """汇总文档条目：与 MeetingChunk 同构的 fields_json/text_md；
    origin_* 记录来源（会议文件里的块），业务级新增的条目 origin 全空。"""

    __tablename__ = "series_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("series_docs.id"))
    seq: Mapped[int]
    chunk_type: Mapped[str]  # req|con|act|q|fact|prose
    section: Mapped[str] = mapped_column(default="")
    ref_id: Mapped[str | None] = mapped_column(nullable=True)  # 汇总文档内重编号
    fields_json: Mapped[str] = mapped_column(Text, default="{}")
    text_md: Mapped[str] = mapped_column(Text, default="")
    # 溯源（可空；源块被删后保留原值作展示，联动时按"源已不存在"处理）
    origin_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("meeting_chunks.id"), nullable=True
    )
    origin_meeting_id: Mapped[int | None] = mapped_column(nullable=True)
    origin_ref_id: Mapped[str | None] = mapped_column(nullable=True)
    origin_meeting_name: Mapped[str] = mapped_column(default="")  # 冗余便于展示

    doc: Mapped[SeriesDoc] = relationship(back_populates="items")


class SeriesDocVersion(Base):
    """汇总文档版本快照：refresh（汇总刷新）| edit（块级编辑）。"""

    __tablename__ = "series_doc_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("series_docs.id"))
    version: Mapped[str]
    content_md: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(default="refresh")  # refresh|edit
    bump: Mapped[str] = mapped_column(default="none")  # major|minor|patch|none
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    doc: Mapped[SeriesDoc] = relationship(back_populates="versions")
