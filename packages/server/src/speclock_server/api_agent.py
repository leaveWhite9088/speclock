"""Agent 读接口（规格索引 / 小业务 / 模块 / diff），按 ``spec.read`` 放行。

这里刻意没有任何能改规格内容的接口——规格库唯一的写入通道是审核单下的 Commit
（见 ``api_cr.py``）；执行侧的写入在 ``api_exec.py``。草稿（Block.draft_*）永远够不着。
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from speclock_core import diffing
from speclock_core import audit
from speclock_core import get_db
from speclock_core import ApiKey, Block, BlockVersion, Capability, CapabilityVersion, ExecutionRecord
from speclock_server.deps import require_permission
from speclock_server.scope import block_project_id, check_project_scope
from speclock_server.responses import BlockHistoryEntry, CapabilityVersionEntry, DiffOut, DiffUnavailableOut
from speclock_server.serializers import block_out
from speclock_core import BlockOut, CapabilityIndexEntry, CapabilityOut, IndexBlock, IndexCapability, IndexBusiness

router = APIRouter(prefix="/api/v1", tags=["agent"])

REF_RE = re.compile(r"^(?P<id>\d+)(?:@(?P<version>\d+\.\d+\.\d+))?$")

def _published_snapshot(db: Session, block: Block, version: str | None) -> BlockVersion:
    if block.status != "published":
        # drafts and archived blocks are invisible to agents
        raise HTTPException(status_code=404, detail=f"block {block.id} not found")
    # 不 pin 时取最新未作废版本（作废时 current_published_version 已回退；
    # 全部作废则其为 None，下面的查询自然 404，模块对 agent 等同未发布）
    target = version or block.current_published_version
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == target)
        .first()
    )
    if bv is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {target}")
    return bv


def _exec_record(db: Session, block_id: int, version: str) -> ExecutionRecord | None:
    return (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.block_id == block_id, ExecutionRecord.version == version)
        .first()
    )


@router.get("/index", response_model=list[IndexBusiness])
def get_index(
    business: str | None = None,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """三层嵌套索引：大业务 → 小业务→ 模块。一次调用拿全图后在树里选模块。
    只含已发布模块；可选过滤：business（大业务名称精确匹配）。
    模块节点带 work_id / execution_status（当前版本的执行状态）；要找待办用 /work。"""
    tree: dict[str, dict[int, dict]] = {}
    count = 0
    records = {
        (r.block_id, r.version): r
        for r in db.query(ExecutionRecord).filter(ExecutionRecord.status != "superseded").all()
    }
    for block in db.query(Block).filter(Block.status == "published").all():
        if block.current_published_version is None:
            # 全部版本已作废：按未发布处理，不出现在索引
            continue
        doc = block.capability
        if key.project_id is not None and doc.business.project_id != key.project_id:
            continue
        if business is not None and doc.business.name != business:
            continue
        rec = records.get((block.id, block.current_published_version))
        docs = tree.setdefault(doc.business.name, {})
        slot = docs.setdefault(doc.id, {"doc": doc, "blocks": []})
        slot["blocks"].append(
            IndexBlock(
                block_id=block.id,
                title=block.title,
                version=block.current_published_version,
                summary=(block.summary or block.draft_content_md.strip())[:50],
                work_id=rec.id if rec else None,
                execution_status=rec.status if rec else None,
            )
        )
        count += 1
    result = [
        IndexBusiness(
            business=dom_name,
            capabilities=[
                IndexCapability(
                    capability_id=doc_id,
                    title=slot["doc"].title,
                    summary=slot["doc"].summary,
                    version=slot["doc"].current_version,
                    blocks=slot["blocks"],
                )
                for doc_id, slot in docs.items()
            ],
        )
        for dom_name, docs in tree.items()
    ]
    audit(db, key.hint, "pull", "index", {"entries": count, "business": business})
    db.commit()
    return result


@router.get("/blocks/{ref}", response_model=BlockOut)
def get_block(ref: str, db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))):
    """Read a published module snapshot. ``ref`` is ``{id}`` or ``{id}@{x.y.z}`` (pin)."""
    m = REF_RE.match(ref)
    if not m:
        raise HTTPException(
            status_code=400, detail="ref must be '{id}' or '{id}@{MAJOR.MINOR.PATCH}'"
        )
    block = db.get(Block, int(m.group("id")))
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {ref} not found")
    check_project_scope(key, block_project_id(block))
    bv = _published_snapshot(db, block, m.group("version"))
    audit(db, key.hint, "pull", f"block:{block.id}@{bv.version}", {})
    db.commit()
    return block_out(bv, _exec_record(db, block.id, bv.version))


@router.get("/blocks/{block_id}/history", response_model=list[BlockHistoryEntry])
def get_block_history(
    block_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """模块的版本历史（从旧到新）：每个版本的级别标签、变更说明、delta、产生它的审核单 /
    Commit、状态（current / deprecated）。内容快照用 ``get_block``（可 pin 版本）读，
    两个版本之间的差异用 ``get_diff``；执行进展不在这里（见 ``/work``）。"""
    block = db.get(Block, block_id)
    if block is None or block.status != "published":
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    check_project_scope(key, block_project_id(block))
    current = block.current_published_version
    out = [
        {
            "version": v.version,
            "level": v.level,
            "status": "current" if v.version == current else "deprecated",
            "superseded_by": None if v.version == current else current,
            "change_note": v.change_note,
            "delta": json.loads(v.delta_json),
            "cr_id": v.cr_id,
            "commit_id": v.commit_id,
            "published_by": v.published_by,
            "published_at": v.published_at,
        }
        for v in block.versions
    ]
    audit(db, key.hint, "pull", f"block:{block_id}/history", {"versions": len(out)})
    db.commit()
    return out


@router.get("/capabilities/{capability_id}/history", response_model=list[CapabilityVersionEntry])
def get_capability_history(
    capability_id: int,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """小业务的版本历史（从旧到新）：每个版本的 manifest（模块 → 版本）、由哪个模块触发、
    变更说明、产生它的审核单 / Commit、状态。某个历史小业务版本的完整快照用
    ``get_capability``（pin 版本）读。"""
    doc = db.get(Capability, capability_id)
    if doc is None or doc.current_version is None:
        raise HTTPException(status_code=404, detail=f"capability {capability_id} not found")
    check_project_scope(key, doc.business.project_id)
    current = doc.current_version
    out = [
        {
            "version": v.version,
            "status": "current" if v.version == current else "deprecated",
            "superseded_by": None if v.version == current else current,
            "manifest": json.loads(v.manifest_json),
            "triggered_by_block_id": v.triggered_by_block_id,
            "change_note": v.change_note,
            "cr_id": v.cr_id,
            "commit_id": v.commit_id,
            "published_by": v.published_by,
            "published_at": v.published_at,
        }
        for v in doc.versions
    ]
    audit(db, key.hint, "pull", f"capability:{capability_id}/history", {"versions": len(out)})
    db.commit()
    return out


def compute_block_diff(
    db: Session, block: Block, from_: str | None, to: str | None
) -> dict:
    """版本间 diff 的核心逻辑，agent / admin 两端点共用。

    from/to 可选，缺省 = 最近两个已发布版本；只有一个已发布版本时返回
    友好提示（调用方原样以 200 返回）而非报错。版本不存在抛 404。
    不做鉴权 / 状态可见性检查（如 agent 仅见 published）——那是调用方
    （端点）的职责；因此这里只按版本号查快照，已归档模块的历史版本同样可比。
    """
    ordered = [v.version for v in block.versions]
    from_ = from_ or (ordered[-2] if len(ordered) >= 2 else None)
    to = to or (ordered[-1] if ordered else None)
    if from_ is None or to is None:
        return {
            "block_id": block.id,
            "message": "该模块目前只有一个已发布版本，暂无可对比的历史版本",
            "versions": ordered,
        }
    old = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == from_)
        .first()
    )
    new = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == to)
        .first()
    )
    if old is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {from_}")
    if new is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {to}")
    d = diffing.delta(json.loads(old.apis_json or "[]"), json.loads(new.apis_json or "[]"))
    # 规则 / 验收条件 delta 一并带给 agent（按稳定 id 匹配）
    d.update(
        diffing.rules_delta(
            json.loads(old.rules_json or "[]"), json.loads(new.rules_json or "[]")
        )
    )
    d.update(
        diffing.acceptance_delta(
            json.loads(old.acceptance_json or "[]"), json.loads(new.acceptance_json or "[]")
        )
    )
    return {
        "block_id": block.id,
        "from": from_,
        "to": to,
        "content_diff": diffing.text_diff(
            old.content_md, new.content_md, fromfile=from_, tofile=to
        ),
        "openapi_diff": diffing.text_diff(
            old.openapi_yaml, new.openapi_yaml, fromfile=from_, tofile=to
        ),
        "delta": d,
        # 机械算出的版本级别标签，仅供参考（与 to 版本发布时记录的标签一致）
        "level": diffing.bump_level(d),
    }


@router.get("/blocks/{block_id}/diff", response_model=DiffOut | DiffUnavailableOut, response_model_by_alias=True)
def get_diff(
    block_id: int,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """版本间 diff。from/to 可选，缺省 = 最近两个已发布版本；只有一个已发布
    版本时返回友好提示（200）而非报错。

    human / agent key 均可用（同一路径，人机共用）：agent key 受 published
    状态与项目隔离约束并写 pull 审计；human key 无限制、不写审计。"""
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"block {block_id} not found")
    is_agent = key.prefix == "agent"
    if is_agent:
        # drafts and archived blocks are invisible to agents
        if block.status != "published":
            raise HTTPException(status_code=404, detail=f"block {block_id} not found")
        check_project_scope(key, block_project_id(block))
    result = compute_block_diff(db, block, from_, to)
    if is_agent:
        audit(db, key.hint, "pull", f"block:{block_id}/diff",
              {"from": result.get("from"), "to": result.get("to")})
        db.commit()
    return result


# ---------- capability-level reads (两级版本的小业务侧) ----------


def _capability_out(db: Session, dv: CapabilityVersion) -> CapabilityOut:
    """manifest 快照 + 每个模块在该版本上的实时执行状态（执行状态是当前状态，不随历史冻结）。"""
    manifest = json.loads(dv.manifest_json)
    entries = []
    for bid, m in manifest.items():
        rec = _exec_record(db, int(bid), m["version"])
        entries.append(
            {
                "block_id": int(bid),
                "title": m["title"],
                "version": m["version"],
                "work_id": rec.id if rec else None,
                "execution_status": rec.status if rec else None,
            }
        )
    return CapabilityOut(
        capability_id=dv.capability_id,
        title=dv.capability.title,
        summary=dv.capability.summary,
        version=dv.version,
        manifest=entries,
        published_at=dv.published_at,
    )


@router.get("/capabilities", response_model=list[CapabilityIndexEntry])
def get_capabilities(
    business: str | None = None,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_permission("spec.read")),
):
    """小业务列表 + 当前小业务版本。没有任何已发布模块的小业务对 agent 不可见。
    可选过滤：business（大业务名称精确匹配）。"""
    out = []
    for doc in db.query(Capability).all():
        if doc.current_version is None:
            continue
        if key.project_id is not None and doc.business.project_id != key.project_id:
            continue
        if business is not None and doc.business.name != business:
            continue
        out.append(
            CapabilityIndexEntry(
                capability_id=doc.id,
                title=doc.title,
                summary=doc.summary,
                business=doc.business.name,
                version=doc.current_version,
            )
        )
    audit(db, key.hint, "pull", "capabilities", {"entries": len(out), "business": business})
    db.commit()
    return out


@router.get("/capabilities/{ref}", response_model=CapabilityOut)
def get_capability(ref: str, db: Session = Depends(get_db), key: ApiKey = Depends(require_permission("spec.read"))):
    """小业务 manifest：该小业务全部模块当前已发布版本清单。支持 ``{id}@{x.y.z}`` pin。"""
    m = REF_RE.match(ref)
    if not m:
        raise HTTPException(
            status_code=400, detail="ref must be '{id}' or '{id}@{MAJOR.MINOR.PATCH}'"
        )
    doc = db.get(Capability, int(m.group("id")))
    if doc is None or doc.current_version is None:
        raise HTTPException(status_code=404, detail=f"capability {ref} not found")
    check_project_scope(key, doc.business.project_id)
    target = m.group("version") or doc.current_version
    dv = (
        db.query(CapabilityVersion)
        .filter(CapabilityVersion.capability_id == doc.id, CapabilityVersion.version == target)
        .first()
    )
    if dv is None:
        raise HTTPException(status_code=404, detail=f"capability {doc.id} has no version {target}")
    audit(db, key.hint, "pull", f"capability:{doc.id}@{dv.version}", {})
    db.commit()
    return _capability_out(db, dv)
