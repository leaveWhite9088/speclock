"""规格写入引擎：把模块草稿快照成不可变版本，并派生小业务版本。

这是内部引擎，**没有任何直接对外的写接口**——对外唯一的写入口是审核单下的 Commit
（见 ``commits.py`` / ``api_cr.py``）。草稿（Block.draft_*）只是 Commit 应用 ops 时的
暂存区：同一个事务里改完就发布，要么整体成功，要么整体回滚，不会残留。
seed.py / inject_ops.py 灌入示例数据时也直接调用这里。

没有"破坏性变更需二次确认"的闸门：需求数据由 Agent 维护、人通过审核单授权。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from speclock import diffing
from speclock.auth import audit
from speclock.executions import sync_block
from speclock.models import Block, BlockVersion, Capability, CapabilityVersion
from speclock.schemas import PublishResult

CONTENT_MD_MIN_LEN = 20  # 业务背景与流程叙述的最短长度（去空白后）


def published_version(db: Session, block: Block, version: str) -> BlockVersion:
    """按版本号取快照；不存在则 404。"""
    bv = (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == version)
        .first()
    )
    if bv is None:
        raise HTTPException(status_code=404, detail=f"block {block.id} has no version {version}")
    return bv


def validate_apis_or_422(apis: list[dict], require_desc: bool = True) -> list[dict]:
    try:
        return diffing.validate_apis(apis, require_desc=require_desc)
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"API 列表不合法: {exc}") from exc


def validate_rules_or_422(rules: list[dict]) -> list[dict]:
    try:
        return diffing.validate_rules(rules)
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"业务规则清单不合法: {exc}") from exc


def validate_acceptance_or_422(items: list[dict]) -> list[dict]:
    try:
        return diffing.validate_acceptance(items)
    except diffing.ApisValidationError as exc:
        raise HTTPException(status_code=422, detail=f"验收条件清单不合法: {exc}") from exc


def with_ids(block: Block, kind: str, items: list[dict]) -> list[dict]:
    """给缺 id 的条目分配稳定 id：编号 = 当前草稿与全部历史快照（含已作废版本）
    里已用最大编号 + 1，因此条目被删除后编号也不会复用。"""
    if kind == "rules":
        draft, attr = block.draft_rules_json, "rules_json"
    else:
        draft, attr = block.draft_acceptance_json, "acceptance_json"
    lists = [json.loads(draft or "[]")] + [
        json.loads(getattr(v, attr) or "[]") for v in block.versions
    ]
    return diffing.assign_item_ids(items, kind, diffing.taken_item_numbers(kind, *lists))


def check_publish_readiness(block: Block) -> list[str]:
    """发布关口「结构完备性」校验：返回全部缺失项（中文），空列表 = 可发布。

    - 业务背景与流程叙述（draft_content_md）非空且至少 20 个字符；
    - 业务规则清单至少 1 条且每条 name/detail 非空；
    - 验收条件清单至少 1 条且每条 name/detail 非空；
    - 每条 API 的 desc（端点语义）非空。
    """
    problems: list[str] = []
    if len((block.draft_content_md or "").strip()) < CONTENT_MD_MIN_LEN:
        problems.append(
            f"业务背景与流程叙述不能为空，且至少 {CONTENT_MD_MIN_LEN} 个字符"
            f"（当前 {len((block.draft_content_md or '').strip())} 个）"
        )
    try:
        rules = diffing.validate_rules(json.loads(block.draft_rules_json or "[]"))
    except diffing.ApisValidationError as exc:
        problems.append(f"业务规则清单不合法：{exc}")
        rules = []
    if not rules:
        problems.append("业务规则清单至少需要 1 条规则（每条含规则名与详述）")
    try:
        acceptance = diffing.validate_acceptance(json.loads(block.draft_acceptance_json or "[]"))
    except diffing.ApisValidationError as exc:
        problems.append(f"验收条件清单不合法：{exc}")
        acceptance = []
    if not acceptance:
        problems.append("验收条件清单至少需要 1 条验收条件（每条含名称与详述）")
    try:
        apis = diffing.validate_apis(
            json.loads(block.draft_apis_json or "[]"), require_desc=False
        )
    except diffing.ApisValidationError as exc:
        problems.append(f"API 列表不合法：{exc}")
    else:
        for i, entry in enumerate(apis):
            if not entry["desc"]:
                problems.append(f"第 {i + 1} 个 API（{entry['name']}）缺少端点语义描述 desc")
    return problems


def derive_capability_version(
    db: Session,
    block: Block,
    level: str,
    actor: str,
    change_note: str,
    cr_id: int | None = None,
    commit_id: int | None = None,
    capability_id: int | None = None,
) -> str:
    """模块发布 / 归档 / 恢复 / 搬动后派生小业务版本：manifest = 该小业务全部已发布模块的
    版本清单。block 只用来标记"由哪个模块触发"；默认派生它所在的小业务，搬动模块时
    要给原小业务也派生一个，所以可以显式指定 capability_id。"""
    cap = db.get(Capability, capability_id or block.capability_id)
    cap_version = diffing.derive_capability_version(cap.current_version, level)
    blocks = db.query(Block).filter(Block.capability_id == cap.id).all()
    manifest = {
        str(b.id): {"title": b.title, "version": b.current_published_version}
        for b in blocks
        if b.status == "published" and b.current_published_version is not None
    }
    db.add(
        CapabilityVersion(
            capability_id=cap.id,
            version=cap_version,
            manifest_json=json.dumps(manifest, ensure_ascii=False),
            triggered_by_block_id=block.id,
            change_note=change_note,
            cr_id=cr_id,
            commit_id=commit_id,
            published_by=actor,
        )
    )
    cap.current_version = cap_version
    audit(
        db,
        actor,
        "publish",
        f"capability:{cap.id}@{cap_version}",
        {"triggered_by_block": block.id, "manifest": manifest, "cr_id": cr_id, "commit_id": commit_id},
    )
    return cap_version


def publish_block(
    db: Session,
    block: Block,
    actor: str,
    change_note: str,
    dry_run: bool = False,
    enforce_readiness: bool = True,
    cr_id: int | None = None,
    commit_id: int | None = None,
    derive_capability: bool = True,
    commit: bool = True,
) -> PublishResult:
    """Snapshot the working draft into a new immutable BlockVersion, then
    (derive_capability=True) derive a new CapabilityVersion for the owning capability.

    dry_run=True 只返回预览（将发布的版本号 / 级别标签 / delta / 预测小业务版本），
    不落库、不写审计。发布关口先做「结构完备性」校验（背景叙述 / 规则清单 / 验收条件 /
    API desc），不满足返回 422 并列出全部缺失项。enforce_readiness=False 仅用于
    inject_ops 恢复先于关口存在的历史数据。

    Commit 引擎在同一事务里发布多个模块：传 commit=False（由调用方统一提交 / 回滚）、
    derive_capability=False（由调用方按小业务合并派生一次）。
    """
    problems = check_publish_readiness(block) if enforce_readiness else []
    if problems:
        raise HTTPException(
            status_code=422,
            detail={"error": "模块结构不完备，不能发布", "missing": problems},
        )
    apis = validate_apis_or_422(json.loads(block.draft_apis_json or "[]"),
                                require_desc=enforce_readiness)
    # 规则 / 验收条件：补齐稳定 id 并写回草稿，快照与 diff 都基于带 id 的清单
    rules = with_ids(block, "rules",
                     validate_rules_or_422(json.loads(block.draft_rules_json or "[]")))
    acceptance = with_ids(block, "acceptance", validate_acceptance_or_422(
        json.loads(block.draft_acceptance_json or "[]")))
    block.draft_rules_json = json.dumps(rules, ensure_ascii=False)
    block.draft_acceptance_json = json.dumps(acceptance, ensure_ascii=False)

    old_apis: list = []
    old_rules: list = []
    old_acceptance: list = []
    if block.current_published_version is not None:
        old_bv = published_version(db, block, block.current_published_version)
        old_apis = json.loads(old_bv.apis_json or "[]")
        old_rules = json.loads(old_bv.rules_json or "[]")
        old_acceptance = json.loads(old_bv.acceptance_json or "[]")
    d = diffing.delta(old_apis, apis)
    d.update(diffing.rules_delta(old_rules, rules))
    d.update(diffing.acceptance_delta(old_acceptance, acceptance))
    groups = diffing.group_delta(d, old_apis, apis)
    # 版本号永不复用：从历史最大号继续递增
    ever = [v.version for v in block.versions]
    base = max(ever, key=diffing.semver_key) if ever else None
    version, level = diffing.next_module_version(base, d)

    if dry_run:
        cap = db.get(Capability, block.capability_id)
        return PublishResult(
            block_id=block.id,
            version=version,
            capability_id=block.capability_id,
            capability_version=diffing.derive_capability_version(cap.current_version, level),
            delta=d,
            level=level,
            groups=groups,
        )

    bv = BlockVersion(
        block=block,  # 同时把新版本挂进 block.versions，保证同一事务内后续的 id 分配看得到它
        version=version,
        content_md=block.draft_content_md,
        rules_json=json.dumps(rules, ensure_ascii=False),
        apis_json=json.dumps(apis, ensure_ascii=False),
        acceptance_json=json.dumps(acceptance, ensure_ascii=False),
        openapi_yaml=diffing.apis_to_openapi_yaml(apis),
        level=level,
        change_note=change_note,
        delta_json=json.dumps(d, ensure_ascii=False),
        cr_id=cr_id,
        commit_id=commit_id,
        published_by=actor,
    )
    db.add(bv)
    db.flush()
    block.current_published_version = version
    block.status = "published"
    # 执行记录跟上新版本：旧版本上未结束的记录被取代，新版本产生一条待领取记录
    sync_block(db, block, actor)
    audit(
        db,
        actor,
        "publish",
        f"block:{block.id}@{version}",
        {"change_note": change_note, "level": level, "delta": d,
         "cr_id": cr_id, "commit_id": commit_id},
    )
    cap_version = ""
    if derive_capability:
        cap_version = derive_capability_version(
            db, block, level, actor, change_note, cr_id=cr_id, commit_id=commit_id
        )
    if commit:
        db.commit()
    return PublishResult(
        block_id=block.id,
        version=version,
        capability_id=block.capability_id,
        capability_version=cap_version,
        delta=d,
        level=level,
        groups=groups,
    )
