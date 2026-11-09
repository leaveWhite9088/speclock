"""搜索：在已发布模块（标题 / 摘要 / 背景 / 规则 / 验收条件 / API）和审核单里找关键词。

只读，按权限放行：搜规格要 ``spec.read``，搜审核单还要 ``cr.read``（没有就只返回规格命中）；
绑定了项目的 key 只能搜本项目。规模小（本地个人使用），直接在内存里做不区分大小写的子串匹配，
不引入全文索引；结果按「模块 → 规则 → 验收条件 → API → 审核单」分组排序，最多 ``limit`` 条。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from speclock import permissions as perms
from speclock.db import get_db
from speclock.models import ApiKey, Block, BlockVersion, ChangeRequest
from speclock.permissions import require_permission

router = APIRouter(prefix="/api/v1", tags=["search"])

SNIPPET_RADIUS = 40
TYPE_ORDER = {"module": 0, "rule": 1, "acceptance": 2, "api": 3, "cr": 4}


def snippet(text: str, q: str) -> str:
    """围绕第一处命中截取一小段；前后被截断时加省略号。"""
    low, ql = text.lower(), q.lower()
    i = low.find(ql)
    if i < 0:
        return text[: SNIPPET_RADIUS * 2]
    start = max(0, i - SNIPPET_RADIUS)
    end = min(len(text), i + len(q) + SNIPPET_RADIUS)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


def _hit(text: str | None, q: str) -> bool:
    return bool(text) and q.lower() in text.lower()


def _api_texts(api: dict) -> list[str]:
    """一个 API 条目里可搜的文字：名称、方法 + 路径、端点语义、请求 / 响应字段名与说明（递归）。"""
    out = [api.get("name", ""), api.get("api", ""), api.get("desc", "")]

    def walk(fields):
        for f in fields or []:
            out.append(f.get("name", ""))
            out.append(f.get("description", ""))
            walk(f.get("children"))

    walk(api.get("request"))
    walk(api.get("response"))
    return [t for t in out if t]


def _block_hits(db: Session, key: ApiKey, q: str, project_id: int | None) -> list[dict]:
    hits: list[dict] = []
    for block in db.query(Block).filter(Block.status == "published").order_by(Block.id).all():
        cap = block.capability
        pid = cap.business.project_id
        if (key.project_id is not None and key.project_id != pid) or (
            project_id is not None and project_id != pid
        ):
            continue
        version = block.current_published_version
        bv = (
            db.query(BlockVersion)
            .filter(BlockVersion.block_id == block.id, BlockVersion.version == version)
            .first()
        )
        if bv is None:
            continue
        where = {
            "block_id": block.id,
            "block_title": block.title,
            "version": version,
            "capability_id": cap.id,
            "capability_title": cap.title,
            "business": cap.business.name,
            "project_id": pid,
        }
        for field, text in (("标题", block.title), ("摘要", block.summary), ("业务背景", bv.content_md)):
            if _hit(text, q):
                hits.append({**where, "type": "module", "field": field, "item_id": "",
                             "title": block.title, "snippet": snippet(text, q)})
                break  # 一个模块只出一条「模块」命中，取最靠前的字段
        for r in json.loads(bv.rules_json or "[]"):
            for field, text in (("规则名", r.get("name")), ("规则详述", r.get("detail"))):
                if _hit(text, q):
                    hits.append({**where, "type": "rule", "field": field, "item_id": r.get("id", ""),
                                 "title": r.get("name", ""), "snippet": snippet(text, q)})
                    break
        for a in json.loads(bv.acceptance_json or "[]"):
            for field, text in (("验收条件名", a.get("name")), ("验收条件详述", a.get("detail"))):
                if _hit(text, q):
                    hits.append({**where, "type": "acceptance", "field": field, "item_id": a.get("id", ""),
                                 "title": a.get("name", ""), "snippet": snippet(text, q)})
                    break
        for api in json.loads(bv.apis_json or "[]"):
            for text in _api_texts(api):
                if _hit(text, q):
                    hits.append({**where, "type": "api", "field": "API", "item_id": api.get("api", ""),
                                 "title": f"{api.get('api', '')} {api.get('name', '')}".strip(),
                                 "snippet": snippet(text, q)})
                    break
    return hits


def _cr_hits(db: Session, key: ApiKey, q: str, project_id: int | None) -> list[dict]:
    hits: list[dict] = []
    for cr in db.query(ChangeRequest).order_by(ChangeRequest.id.desc()).all():
        if (key.project_id is not None and key.project_id != cr.project_id) or (
            project_id is not None and project_id != cr.project_id
        ):
            continue
        acceptance = json.loads(cr.acceptance_json or "[]")
        texts = [
            ("标题", cr.title),
            ("为什么变", cr.intent),
            ("变成什么样", cr.expected_outcome),
            ("不再成立的旧认知", " ".join(json.loads(cr.obsolete_json or "[]"))),
            ("验收条件", " ".join(f"{a.get('name', '')} {a.get('detail', '')}" for a in acceptance)),
            ("影响说明", cr.impact_note),
            ("内部整理的理由", cr.kind_reason),
        ]
        for field, text in texts:
            if _hit(text, q):
                hits.append({"type": "cr", "cr_id": cr.id, "status": cr.status, "kind": cr.kind,
                             "project_id": cr.project_id, "field": field, "item_id": "",
                             "title": cr.title, "snippet": snippet(text, q)})
                break
    return hits


@router.get("/search")
def search(
    q: str = Query(..., description="关键词（不区分大小写的子串匹配）"),
    project_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """在已发布模块的当前版本和（有 cr.read 时）审核单里搜索关键词。返回命中的位置与片段，
    前端据此高亮并跳到对应模块 / 规则 / 审核单。"""
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="q 不能为空")
    hits = _block_hits(db, key, q, project_id)
    if "cr.read" in perms.role_permissions(key.role):
        hits += _cr_hits(db, key, q, project_id)
    hits.sort(key=lambda h: TYPE_ORDER[h["type"]])  # 稳定排序：同类型保持原有顺序
    total = len(hits)
    return {"query": q, "total": total, "truncated": total > limit, "hits": hits[:limit]}
