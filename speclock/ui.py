"""Minimal human-facing UI (Jinja2 + vanilla JS).

Pages: document tree, module editor (业务描述拆为 背景叙述 / 规则清单 /
边界与异常 三区 + API 填表区 + 非功能性需求，全程无 YAML), diff view,
publish, proposal inbox, ack board, document version history. Auth via
?key=human-... query parameter — MVP grade, single-operator tool.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from speclock.auth import hash_key, key_hint
from speclock.db import get_db
from speclock.models import (
    Ack,
    ApiKey,
    AuditLog,
    Block,
    Document,
    DocumentVersion,
    Domain,
    Project,
    Proposal,
)

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _render_md(text: str) -> str:
    """业务描述 / 非功能性需求的 Markdown → HTML（查看页渲染用）。"""
    import markdown
    return markdown.markdown(text or "", extensions=["tables", "fenced_code", "sane_lists"])


templates.env.filters["md"] = _render_md


def _check_key(request: Request, db: Session) -> str | RedirectResponse:
    """UI 页面级校验：?key= 必须是库中存在的 human-* key，否则重定向登录页。
    （此前只查前缀，key 失效后页面照开、写接口才 401，用户无法自查。）"""
    key = request.query_params.get("key", "")
    rec = None
    if key:
        rec = (
            db.query(ApiKey)
            .filter(ApiKey.key == hash_key(key), ApiKey.prefix == "human")
            .first()
        )
    if rec is None:
        return RedirectResponse(url="/ui/login?error=1")
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
            "rules": json.loads(block.draft_rules_json or "[]"),
            "edge_md": block.draft_edge_md,
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
    rules = json.loads(bv.rules_json or "[]") if bv else []
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
            "rules": rules,
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
    ordered = sorted(versions, key=lambda v: versions[v].id)
    # 默认对比：上一版 → 当前版；只有一个版本时不默认（from 留空，页面友好提示）
    if not to and ordered:
        to = ordered[-1]
    if not from_ and len(ordered) >= 2:
        from_ = ordered[-2]

    summary = None
    groups = []
    rules_delta: dict[str, list[str]] = {}
    content_lines: list[str] = []
    nfr_lines: list[str] = []
    if from_ and to and from_ != to and from_ in versions and to in versions:
        old, new = versions[from_], versions[to]
        old_apis = json.loads(old.apis_json or "[]")
        new_apis = json.loads(new.apis_json or "[]")
        d = diffing.delta(old_apis, new_apis)
        groups = diffing.group_delta(d, old_apis, new_apis)
        rules_delta = diffing.rules_delta(
            json.loads(old.rules_json or "[]"), json.loads(new.rules_json or "[]")
        )
        summary = {
            "from": from_,
            "to": to,
            "breaking": diffing.is_breaking(d),
            "added": len(d["added"]),
            "modified": len(d["modified"]),
            "removed": len(d["removed"]),
            "rules_added": len(rules_delta["rules_added"]),
            "rules_removed": len(rules_delta["rules_removed"]),
            "rules_modified": len(rules_delta["rules_modified"]),
            "change_note": new.change_note,
        }
        content_lines = diffing.text_diff(old.content_md, new.content_md, from_, to).splitlines()
        nfr_lines = diffing.text_diff(old.nfr_md, new.nfr_md, from_, to).splitlines()
    return templates.TemplateResponse(
        request,
        "diff.html",
        {
            "key": key,
            "block": block,
            "versions": ordered,
            "from": from_,
            "to": to,
            "summary": summary,
            "groups": groups,
            "rules_delta": rules_delta,
            "content_lines": content_lines,
            "nfr_lines": nfr_lines,
        },
    )


@router.get("/ui/mcp", response_class=HTMLResponse)
def mcp_page(request: Request, db: Session = Depends(get_db)):
    """AI 接入（MCP）页：说明、可复制配置、工具清单、AI 最近活动。"""
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    import sys

    agent_rec = (
        db.query(ApiKey).filter(ApiKey.prefix == "agent").order_by(ApiKey.id).first()
    )
    # 密钥哈希化后系统不再保存明文，配置里只能给占位符——
    # 用户到「密钥管理」页新建 agent key（仅此一次可见）后自行粘贴
    agent_key = "<粘贴你的 agent key（密钥管理页生成，仅此一次可见）>"
    agent_hint = agent_rec.hint if agent_rec else ""
    # 对外地址：speclock.toml 当前环境配了 public_url 就用它（服务器场景），
    # 否则按访问地址动态生成（本地场景）
    from speclock.settings import load_settings

    base_url = load_settings().public_url or str(request.base_url).rstrip("/")
    config = {
        "mcpServers": {
            "speclock": {
                "command": sys.executable,
                "args": ["-m", "speclock.mcp_server"],
                "env": {
                    "SPECLOCK_URL": base_url,
                    "SPECLOCK_KEY": agent_key,
                },
            }
        }
    }
    activities = (
        db.query(AuditLog)
        .filter(AuditLog.actor.like("agent-%"))
        .order_by(AuditLog.id.desc())
        .limit(50)
        .all()
    )
    config_json = json.dumps(config, indent=2, ensure_ascii=False)
    tools_md = "\n".join(f"- `{name}`：{desc}" for name, desc in MCP_TOOLS)
    brief = (
        "# SpecLock · AI 接入说明\n\n"
        "你是一名开发 AI agent。SpecLock 是本项目的业务文档单一事实源："
        "所有业务文档在这里维护并版本化，你通过它的 MCP server 以只读方式获取已发布文档。"
        "请按以下步骤自行完成接入。\n\n"
        "## 1. 写入 MCP 配置\n\n"
        "把下面的 JSON 合并到项目根目录的 `.mcp.json`"
        "（若已有 `mcpServers` 字段，只合并其中 `speclock` 一项），"
        "然后重启你的客户端使配置生效。MCP server 以 stdio 方式启动。\n\n"
        "```json\n" + config_json + "\n```\n\n"
        f"## 2. 你可用的工具（{len(MCP_TOOLS)} 个）\n\n"
        + tools_md + "\n\n"
        "## 3. 使用规则\n\n"
        "- 先调用 `get_index` 拿 大业务→小业务→模块 的三层索引树，在树里选中目标模块后用 `get_block` 拉取，不要逐个全量拉取。\n"
        "- 索引树每个模块节点都带 `completed` 完成标记：迭代时只做 `completed=false` 的模块"
        "（也可用 `get_index(incomplete_only=true)` 直接过滤），不要重做已完成模块。\n"
        "- 实现前用 `get_document` / `get_block` 的版本参数 pin 住快照；实现完成后调用 `ack_block` 回执「已按 模块@版本 实现」。\n"
        "- 你只能读到已发布版本；草稿与已归档内容对你不可见。\n"
        "- 你没有任何修改文档的工具。发现文档有误或缺失时，用 `submit_proposal` 提交变更提案"
        "（你唯一的写出口），经人审批发布后才生效；用 `get_proposal` 轮询提案状态。\n"
        "- 需要对比两个版本时调用 `get_diff`，按结构化 diff 增量调整实现。\n"
    )
    return templates.TemplateResponse(
        request,
        "mcp.html",
        {
            "key": key,
            "config": config,
            "agent_key": agent_key,
            "agent_hint": agent_hint,
            "tools": MCP_TOOLS,
            "activities": activities,
            "brief": brief,
        },
    )


MCP_TOOLS = [
    ("get_index", "大业务→小业务→模块 三层索引树，模块节点带 completed 完成标记（AI 先取索引树选块，再按需拉块；迭代时只做 completed=false 的模块）"),
    ("get_block", "读取一个模块的已发布版本，可 pin 版本号锁定快照"),
    ("get_document", "读取文档 manifest（模块→版本清单），可 pin 历史文档版本回放快照"),
    ("get_diff", "两个已发布版本之间的结构化 + 文本 diff"),
    ("ack_block", "回执：声明「已按 模块@版本 实现」"),
    ("submit_proposal", "提交变更提案——AI 唯一的写出口，需人审批发布后才生效"),
    ("get_proposal", "轮询提案状态（submitted / published / rejected）"),
]


@router.get("/ui/archive", response_class=HTMLResponse)
def archive_page(request: Request, db: Session = Depends(get_db)):
    """归档管理页：全部归档模块一览，支持恢复 / 彻底删除。"""
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    rows = [
        (b, b.document, b.document.domain)
        for b in db.query(Block).filter(Block.status == "archived").order_by(Block.id).all()
    ]
    return templates.TemplateResponse(
        request, "archive.html", {"key": key, "rows": rows}
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


@router.get("/ui/keys", response_class=HTMLResponse)
def keys_page(request: Request, db: Session = Depends(get_db)):
    """密钥管理页：human/agent key 的列表、新建、删除。"""
    key = _check_key(request, db)
    if not isinstance(key, str):
        return key
    keys = db.query(ApiKey).order_by(ApiKey.id).all()
    projects = db.query(Project).order_by(Project.id).all()
    return templates.TemplateResponse(
        request,
        "keys.html",
        {
            "key": key,
            "keys": keys,
            "current_hint": key_hint(key),
            "projects": projects,
            "project_names": {p.id: p.name for p in projects},
        },
    )
