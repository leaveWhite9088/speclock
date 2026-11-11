"""Commit 引擎：已批准审核单下的一次原子写入。

一个 Commit = 一组有序 ops，作用于该审核单所在项目里的大业务 / 小业务 / 模块，
可涉及多个 Block、跨多个 Capability。整个 Commit 在**一个事务**里完成：任何一条
op 失败（id 不存在、结构不合法、模块不完备……）都整体回滚，不留半成品；全部成功即
发布——不经过草稿、不需要再有人确认（授权已经在审核单上完成）。

ops（``op`` 字段）：

- ``create_business``     {name, ref?}
- ``update_business``     {id, name}
- ``create_capability``   {business, title, summary?, ref?}
- ``update_capability``   {id, title?, summary?}
- ``create_block``        {capability, title, summary?, content_md, rules, apis, acceptance, surfaces?, ref?}
- ``update_block``        {id, title?, summary?, content_md?,
                           rules? | rule_ops?, apis? | api_ops?, acceptance? | acceptance_ops?, surfaces?}
                          ``surfaces``：模块涉及哪些端（["前端", "后端"]，名字自由，整体替换）；每个端发布后各有一条
                          执行记录。验收条件可带 ``surfaces``（由哪些端负责），不写 = 所有端都要覆盖；
                          不声明端的模块行为和以前一样。
- ``archive_block``       {id}
- ``restore_block``       {id}
- ``move_block``          {id, capability}   把已发布模块搬到同项目的另一个小业务（模块的身份、
                          历史版本、执行记录都保留，不产生新的模块版本；两个小业务各派生一个版本）

引用：同一 Commit 里先建的对象可以起 ``ref`` 名，后面的 op 用 ``"$名"`` 引用其 id；
已有对象用整数 id。所有对象必须属于审核单所在项目，否则 404。

整体替换（``rules`` / ``apis`` / ``acceptance``）里条目带 id 才被视为同一条，不带 id
的是新增；``*_ops`` 是增量：按稳定 id 定位，upsert+id 修改、upsert 无 id 新增、delete+id
删除，id 不存在 → 409。同一个字段不能同时给整体替换和增量。

发布与版本：本次改动内容的模块各发布一个新版本（版本级别标签由代码机械算出）；每个
受影响的小业务在整个 Commit 结束时**只派生一个**新版本。归档 / 恢复模块也会派生
小业务版本（MINOR）。
"""

from __future__ import annotations

import json
import re

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from speclock_core import diffing, events
from speclock_core.auth import audit
from speclock_core.errors import ApiError
from speclock_core.engine import (
    derive_capability_version,
    publish_block,
    validate_acceptance_or_422,
    validate_surfaces_or_422,
    validate_apis_or_422,
    validate_rules_or_422,
    with_ids,
)
from speclock_core.models import Block, Business, Capability, ChangeRequest, Commit, utcnow
from speclock_core.schemas import AcceptanceEntry, ApiEntry, ApiOp, ItemEntry, ItemOp

MAX_OPS = 200
REF_HINT = "引用写法：创建它的 op 里给 \"ref\": \"biz\"，后面引用处写字符串 \"$biz\"（带 $ 前缀）"
REF_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
LEVEL_RANK = {"patch": 0, "minor": 1, "initial": 1, "major": 2}

OP_KEYS = {
    "create_business": {"op", "name", "ref"},
    "update_business": {"op", "id", "name"},
    "create_capability": {"op", "business", "title", "summary", "ref"},
    "update_capability": {"op", "id", "title", "summary"},
    "create_block": {"op", "capability", "title", "summary", "content_md",
                     "rules", "apis", "acceptance", "surfaces", "ref"},
    "update_block": {"op", "id", "title", "summary", "content_md", "rules", "apis",
                     "acceptance", "rule_ops", "api_ops", "acceptance_ops", "surfaces"},
    "archive_block": {"op", "id"},
    "restore_block": {"op", "id"},
    "move_block": {"op", "id", "capability"},
}


def _422(msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail=msg)


def _model(model, data, where: str):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])} {e['msg']}" for e in exc.errors()
        )
        raise _422(f"{where} 不合法：{errs}") from exc


def _nonempty_str(op: dict, key: str, required: bool = True) -> str | None:
    if key not in op or op[key] is None:
        if required:
            raise _422(f"缺少 {key}")
        return None
    value = op[key]
    if not isinstance(value, str) or (required and not value.strip()):
        raise _422(f"{key} 必须是非空字符串" if required else f"{key} 必须是字符串")
    return value.strip() if key in ("name", "title") else value


# ---------- 增量 ops 的规范化与应用（按稳定 id / API 名定位） ----------


def normalize_api_ops(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise _422("api_ops 必须是数组")
    out = []
    for n, r in enumerate(raw, 1):
        op = _model(ApiOp, r, f"api_ops 第 {n} 条")
        try:
            method, path = diffing.parse_api_name(op.api)
            entry = None
            if op.op == "upsert":
                if op.entry is None:
                    raise _422(f"api_ops 第 {n} 条：upsert 必须携带 entry（api={op.api}）")
                if diffing.parse_api_name(op.entry.api) != (method, path):
                    raise _422(
                        f"api_ops 第 {n} 条：entry.api（{op.entry.api}）必须与顶层 api（{op.api}）一致"
                    )
                entry = diffing.validate_apis([op.entry.model_dump()])[0]
            elif op.entry is not None:
                raise _422(f"api_ops 第 {n} 条：delete 不能携带 entry（api={op.api}）")
        except diffing.ApisValidationError as exc:
            raise _422(f"API 变更不合法: {exc}") from exc
        out.append({"op": op.op, "api": f"{method} {path}", "entry": entry})
    return out


def normalize_item_ops(raw: object, kind: str) -> list[dict]:
    prefix, label = diffing.ITEM_KINDS[kind]
    if not isinstance(raw, list):
        raise _422(f"{label} ops 必须是数组")
    out = []
    for n, r in enumerate(raw, 1):
        op = _model(ItemOp, r, f"{label} ops 第 {n} 条")
        if op.op == "upsert":
            if op.entry is None:
                raise _422(f"{label} ops 第 {n} 条：upsert 必须携带 entry")
            if op.id and op.entry.id and op.entry.id != op.id:
                raise _422(
                    f"{label} ops 第 {n} 条：entry.id（{op.entry.id}）必须与顶层 id（{op.id}）一致"
                )
        else:
            if not op.id:
                raise _422(f"{label} ops 第 {n} 条：delete 必须带 id")
            if op.entry is not None:
                raise _422(f"{label} ops 第 {n} 条：delete 不能携带 entry（id={op.id}）")
        entry = None
        if op.entry is not None:
            try:
                entry = diffing.validate_items([op.entry.model_dump()], kind)[0]
            except diffing.ApisValidationError as exc:
                raise _422(f"{label}变更不合法: {exc}") from exc
        item_id = (op.id or (entry["id"] if entry else "") or "").strip() or None
        if item_id and diffing._item_id_no(item_id, prefix) is None:
            raise _422(f"{label}变更不合法: id {item_id!r} 应形如 {prefix}-1")
        if entry is not None and item_id:
            entry["id"] = item_id
        out.append({"op": op.op, "id": item_id, "entry": entry})
    return out


def apply_api_ops(current: list[dict], ops: list[dict]) -> list[dict]:
    """按 op 顺序应用到当前 API 列表（按 api 字段定位）：upsert 命中原位替换、
    未命中追加末尾；delete 未命中 409。"""
    merged = list(current)
    for op in ops:
        key = op["api"]
        idx = next((i for i, e in enumerate(merged) if e.get("api") == key), None)
        if op["op"] == "upsert":
            if idx is None:
                merged.append(op["entry"])
            else:
                merged[idx] = op["entry"]
        else:
            if idx is None:
                raise HTTPException(
                    status_code=409, detail=f"api_ops delete 未命中：API {key} 在模块里不存在"
                )
            merged.pop(idx)
    return merged


def apply_item_ops(current: list[dict], ops: list[dict], label: str) -> list[dict]:
    """按 op 顺序应用到规则 / 验收条件清单（按稳定 id 定位）：upsert+id 原位修改
    （id 不存在 409）；upsert 不带 id = 新增（id 稍后分配）；delete+id 删除（id 不存在 409）。"""
    merged = list(current)
    for op in ops:
        item_id = op.get("id")
        idx = next(
            (i for i, e in enumerate(merged) if item_id and e.get("id") == item_id), None
        )
        if op["op"] == "upsert":
            if item_id is None:
                merged.append({**op["entry"], "id": ""})
            elif idx is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"{label} ops upsert 未命中：{item_id} 在模块里不存在",
                )
            else:
                merged[idx] = {**op["entry"], "id": item_id}
        else:
            if idx is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"{label} ops delete 未命中：{item_id} 在模块里不存在",
                )
            merged.pop(idx)
    return merged


# ---------- Commit 应用 ----------


class _Ctx:
    """一次 Commit 应用过程中的共享状态。"""

    def __init__(self, db: Session, cr: ChangeRequest, commit: Commit, actor: str):
        self.db = db
        self.cr = cr
        self.commit = commit
        self.actor = actor
        self.refs: dict[str, object] = {}
        self.ref_info: dict[str, dict] = {}
        self.touched: dict[int, dict] = {}  # block_id -> {block, created}
        self.archived: dict[int, Block] = {}
        self.restored: dict[int, Block] = {}
        self.moved: dict[int, tuple[int, Block]] = {}  # block_id -> (原小业务 id, block)

    # --- 引用解析 ---

    def _resolve(self, value, model, what: str):
        if isinstance(value, str) and value.startswith("$"):
            obj = self.refs.get(value)
            if obj is None or not isinstance(obj, model):
                raise _422(f"引用 {value} 不存在或不是{what}（ref 必须先于引用它的 op 创建）")
            return obj
        if isinstance(value, bool) or not isinstance(value, int):
            hint = REF_HINT
            if isinstance(value, dict) and "$ref" in value:
                hint = f"不是 {{\"$ref\": ...}} 这种写法；{REF_HINT}"
            elif isinstance(value, str) and f"${value}" in self.refs:
                hint = f"你是不是想写 '${value}'？{REF_HINT}"
            raise _422(f"{what} 必须是整数 id 或引用字符串，got {value!r}。{hint}")
        obj = self.db.get(model, value)
        if obj is None or self._project_of(obj) != self.cr.project_id:
            raise HTTPException(
                status_code=404, detail=f"{what} {value} 不存在，或不属于审核单所在项目"
            )
        return obj

    def _project_of(self, obj) -> int:
        if isinstance(obj, Business):
            return obj.project_id
        if isinstance(obj, Capability):
            return obj.business.project_id
        return obj.capability.business.project_id

    def business(self, value) -> Business:
        return self._resolve(value, Business, "大业务")

    def capability(self, value) -> Capability:
        return self._resolve(value, Capability, "小业务")

    def block(self, value) -> Block:
        return self._resolve(value, Block, "模块")

    def register_ref(self, op: dict, obj, kind: str) -> None:
        ref = op.get("ref")
        if ref is None:
            return
        if not isinstance(ref, str) or not REF_NAME_RE.match(ref):
            raise _422(f"ref {ref!r} 不合法：字母开头，仅含字母 / 数字 / _ / -，最长 32")
        key = f"${ref}"
        if key in self.refs:
            raise _422(f"ref {key} 重复")
        self.refs[key] = obj
        self.ref_info[key] = {"type": kind, "id": obj.id}


def _op_create_business(ctx: _Ctx, op: dict) -> None:
    obj = Business(project_id=ctx.cr.project_id, name=_nonempty_str(op, "name"))
    ctx.db.add(obj)
    ctx.db.flush()
    ctx.register_ref(op, obj, "business")


def _op_update_business(ctx: _Ctx, op: dict) -> None:
    obj = ctx.business(op.get("id"))
    obj.name = _nonempty_str(op, "name")


def _op_create_capability(ctx: _Ctx, op: dict) -> None:
    business = ctx.business(op.get("business"))
    obj = Capability(
        business_id=business.id,
        title=_nonempty_str(op, "title"),
        summary=_nonempty_str(op, "summary", required=False) or "",
    )
    ctx.db.add(obj)
    ctx.db.flush()
    ctx.register_ref(op, obj, "capability")


def _op_update_capability(ctx: _Ctx, op: dict) -> None:
    obj = ctx.capability(op.get("id"))
    title = _nonempty_str(op, "title", required=False)
    summary = _nonempty_str(op, "summary", required=False)
    if title is None and summary is None:
        raise _422("title 或 summary 至少传一个")
    if title is not None:
        obj.title = title
    if summary is not None:
        obj.summary = summary


def _coerce_apis(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise _422("apis 必须是数组")
    items = [_model(ApiEntry, e, f"apis 第 {i} 项").model_dump() for i, e in enumerate(raw, 1)]
    # desc 的缺失留给发布关口的结构完备性校验，和其他缺失项一起一次列全
    return validate_apis_or_422(items, require_desc=False)


def _coerce_items(raw: object, kind: str) -> list[dict]:
    _, label = diffing.ITEM_KINDS[kind]
    if not isinstance(raw, list):
        raise _422(f"{kind} 必须是数组")
    model = AcceptanceEntry if kind == "acceptance" else ItemEntry
    items = [_model(model, e, f"{label} 第 {i} 项").model_dump() for i, e in enumerate(raw, 1)]
    if kind == "rules":
        return validate_rules_or_422(items)
    return validate_acceptance_or_422(items)


def _op_create_block(ctx: _Ctx, op: dict) -> None:
    cap = ctx.capability(op.get("capability"))
    block = Block(
        capability_id=cap.id,
        title=_nonempty_str(op, "title"),
        summary=_nonempty_str(op, "summary", required=False) or "",
        draft_content_md=_nonempty_str(op, "content_md", required=False) or "",
    )
    block.draft_apis_json = json.dumps(_coerce_apis(op.get("apis", [])), ensure_ascii=False)
    rules = _coerce_items(op.get("rules", []), "rules")
    acceptance = _coerce_items(op.get("acceptance", []), "acceptance")
    block.draft_surfaces_json = json.dumps(
        validate_surfaces_or_422(op.get("surfaces", [])), ensure_ascii=False)
    ctx.db.add(block)
    ctx.db.flush()
    block.draft_rules_json = json.dumps(with_ids(block, "rules", rules), ensure_ascii=False)
    block.draft_acceptance_json = json.dumps(
        with_ids(block, "acceptance", acceptance), ensure_ascii=False
    )
    ctx.touched[block.id] = {"block": block, "created": True}
    ctx.register_ref(op, block, "block")


def _update_list(block: Block, op: dict, field: str, ops_field: str, kind: str | None):
    """返回 (新清单, 是否变化)。kind=None 表示 API 列表。"""
    attr = {"rules": "draft_rules_json", "apis": "draft_apis_json",
            "acceptance": "draft_acceptance_json"}[field]
    current = json.loads(getattr(block, attr) or "[]")
    if field in op and ops_field in op:
        raise _422(f"{field}（整体替换）与 {ops_field}（增量）不能同时给")
    if field in op:
        items = _coerce_apis(op[field]) if kind is None else with_ids(
            block, kind, _coerce_items(op[field], kind)
        )
    elif ops_field in op:
        if kind is None:
            items = validate_apis_or_422(
                apply_api_ops(current, normalize_api_ops(op[ops_field])), require_desc=False
            )
        else:
            _, label = diffing.ITEM_KINDS[kind]
            merged = apply_item_ops(current, normalize_item_ops(op[ops_field], kind), label)
            checked = (validate_rules_or_422 if kind == "rules" else validate_acceptance_or_422)(
                merged
            )
            items = with_ids(block, kind, checked)
    else:
        return current, False
    return items, items != current


def _op_update_block(ctx: _Ctx, op: dict) -> None:
    block = ctx.block(op.get("id"))
    if block.status == "archived":
        raise ApiError("block_archived", f"模块 {block.id} 已归档，请先 restore_block")
    if block.id in ctx.archived:
        raise HTTPException(status_code=409, detail=f"模块 {block.id} 在本 Commit 中已被归档")
    changed_meta = False
    title = _nonempty_str(op, "title", required=False)
    if title is not None and title != block.title:
        block.title, changed_meta = title, True
    summary = _nonempty_str(op, "summary", required=False)
    if summary is not None and summary != block.summary:
        block.summary, changed_meta = summary, True

    content_changed = False
    content = _nonempty_str(op, "content_md", required=False)
    if content is not None and content != block.draft_content_md:
        block.draft_content_md, content_changed = content, True
    for field, ops_field, kind, attr in (
        ("rules", "rule_ops", "rules", "draft_rules_json"),
        ("apis", "api_ops", None, "draft_apis_json"),
        ("acceptance", "acceptance_ops", "acceptance", "draft_acceptance_json"),
    ):
        items, changed = _update_list(block, op, field, ops_field, kind)
        if changed:
            setattr(block, attr, json.dumps(items, ensure_ascii=False))
            content_changed = True
    if "surfaces" in op:
        surfaces = validate_surfaces_or_422(op["surfaces"])
        if surfaces != json.loads(block.draft_surfaces_json or "[]"):
            block.draft_surfaces_json = json.dumps(surfaces, ensure_ascii=False)
            content_changed = True
    if content_changed:
        entry = ctx.touched.setdefault(block.id, {"block": block, "created": False})
        entry["block"] = block
    elif not changed_meta:
        raise _422(f"模块 {block.id} 没有产生任何变化（内容、标题、简述都与现状一致）")


def _op_archive_block(ctx: _Ctx, op: dict) -> None:
    block = ctx.block(op.get("id"))
    if block.id in ctx.touched:
        raise HTTPException(
            status_code=409, detail=f"模块 {block.id} 在本 Commit 中已被改动，不能再归档"
        )
    if block.status != "published":
        raise HTTPException(
            status_code=409, detail=f"模块 {block.id} 当前是 {block.status}，只有已发布模块能归档"
        )
    block.status = "archived"
    block.archived_at = utcnow()
    ctx.archived[block.id] = block


def _op_restore_block(ctx: _Ctx, op: dict) -> None:
    block = ctx.block(op.get("id"))
    if block.status != "archived":
        raise HTTPException(
            status_code=409, detail=f"模块 {block.id} 当前是 {block.status}，不是已归档"
        )
    block.status = "published"
    block.archived_at = None
    ctx.restored[block.id] = block


def _op_move_block(ctx: _Ctx, op: dict) -> None:
    block = ctx.block(op.get("id"))
    target = ctx.capability(op.get("capability"))
    if block.status != "published":
        raise HTTPException(
            status_code=409, detail=f"模块 {block.id} 当前是 {block.status}，只有已发布模块能搬动"
        )
    if block.id in ctx.archived:
        raise HTTPException(status_code=409, detail=f"模块 {block.id} 在本 Commit 中已被归档")
    if block.id in ctx.moved:
        raise HTTPException(status_code=409, detail=f"模块 {block.id} 在本 Commit 中已被搬动过")
    if block.capability_id == target.id:
        raise _422(f"模块 {block.id} 已经在小业务 {target.id} 下，无需搬动")
    ctx.moved[block.id] = (block.capability_id, block)
    block.capability_id = target.id
    ctx.db.flush()


HANDLERS = {
    "create_business": _op_create_business,
    "update_business": _op_update_business,
    "create_capability": _op_create_capability,
    "update_capability": _op_update_capability,
    "create_block": _op_create_block,
    "update_block": _op_update_block,
    "archive_block": _op_archive_block,
    "restore_block": _op_restore_block,
    "move_block": _op_move_block,
}


def validate_ops_shape(ops: object) -> list[dict]:
    if not isinstance(ops, list) or not ops:
        raise _422("ops 必须是非空数组")
    if len(ops) > MAX_OPS:
        raise _422(f"一个 Commit 最多 {MAX_OPS} 条 op")
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict) or op.get("op") not in HANDLERS:
            raise _422(f"第 {i} 条 op 的 op 字段必须是 {sorted(HANDLERS)} 之一")
        extra = sorted(set(op) - OP_KEYS[op["op"]])
        if extra:
            raise _422(
                f"第 {i} 条 op（{op['op']}）含未知字段：{'、'.join(extra)}；"
                f"允许的字段：{'、'.join(sorted(OP_KEYS[op['op']]))}"
            )
    return ops


def validate_covers(cr: ChangeRequest, covers: list[str]) -> list[str]:
    valid = {a["id"] for a in json.loads(cr.acceptance_json or "[]")}
    unknown = sorted(set(covers) - valid)
    if unknown:
        raise _422(f"covers 含审核单里不存在的验收条件：{'、'.join(unknown)}")
    return sorted(set(covers), key=lambda s: int(s.split("-")[1]))


def _rewrap(exc: HTTPException, detail: object) -> HTTPException:
    """换一段 detail 重新抛，保留原来的状态码和错误码。"""
    if isinstance(exc, ApiError):
        return ApiError(exc.code, detail)
    return HTTPException(status_code=exc.status_code, detail=detail)


def _wrap(i: int, op: dict, exc: HTTPException) -> HTTPException:
    where = f"第 {i} 条 op（{op['op']}）"
    if isinstance(exc.detail, str):
        return _rewrap(exc, f"{where}：{exc.detail}")
    if isinstance(exc.detail, dict):
        return _rewrap(exc, {"op_index": i, "op": op["op"], **exc.detail})
    return exc


def _entry_key(kind: str, entry: dict) -> tuple:
    """条目的规范形式（忽略编号，只看内容），用来比较「条目总和」是否不变。"""
    clean = {k: v for k, v in entry.items() if k != "id"}
    return (kind, json.dumps(clean, ensure_ascii=False, sort_keys=True))


def apply_commit(
    db: Session,
    cr: ChangeRequest,
    ops: object,
    covers: list[str],
    change_note: str,
    actor: str,
    dry_run: bool = False,
) -> tuple[Commit, dict]:
    """在审核单 cr 下原子应用 ops 并发布。dry_run=True 完整执行后回滚（预览：
    会得到的版本号 / 级别标签 / delta），不落库、不写审计。"""
    if cr.status != "approved":
        raise ApiError(
            "cr_state_conflict", f"审核单是 {cr.status}，只有已批准（approved）的才能提交 Commit"
        )
    if isinstance(ops, list) and not ops:
        # 「只补覆盖」的 Commit：之前的 Commit 漏写了 covers，事后补一条声明。不改规格，
        # 但必须声明要补哪些验收条件，并写明为什么（声明是否属实仍由验证环节负责）
        if not covers:
            raise _422("ops 为空时，必须在 covers 里写明要补覆盖的验收条件（AC-n）")
        if not change_note.strip():
            raise _422("只补覆盖、不改规格的 Commit 必须在 change_note 里写明原因")
    else:
        ops = validate_ops_shape(ops)
    covers = validate_covers(cr, covers)
    note = change_note.strip() or f"审核单 #{cr.id}「{cr.title}」"
    seq = max((c.seq for c in cr.commits), default=0) + 1
    commit = Commit(
        cr_id=cr.id,
        seq=seq,
        ops_json=json.dumps(ops, ensure_ascii=False),
        covers_json=json.dumps(covers),
        change_note=note,
        created_by=actor,
    )
    db.add(commit)
    try:
        db.flush()
        ctx = _Ctx(db, cr, commit, actor)
        for i, op in enumerate(ops, 1):
            try:
                HANDLERS[op["op"]](ctx, op)
            except HTTPException as exc:
                raise _wrap(i, op, exc) from exc
        db.flush()

        blocks_out = []
        cap_levels: dict[int, list[str]] = {}
        cap_trigger: dict[int, Block] = {}
        for block_id, info in ctx.touched.items():
            block = info["block"]
            try:
                result = publish_block(
                    db, block, actor=actor, change_note=note,
                    cr_id=cr.id, commit_id=commit.id,
                    derive_capability=False, commit=False,
                )
            except HTTPException as exc:
                raise _rewrap(
                    exc,
                    {"block_id": block.id, "title": block.title, **exc.detail}
                    if isinstance(exc.detail, dict)
                    else f"模块 {block.id}「{block.title}」：{exc.detail}",
                ) from exc
            cap_levels.setdefault(block.capability_id, []).append(result.level)
            cap_trigger.setdefault(block.capability_id, block)
            blocks_out.append(
                {
                    "block_id": block.id,
                    "title": block.title,
                    "capability_id": block.capability_id,
                    "version": result.version,
                    "level": result.level,
                    "created": info["created"],
                    "delta": result.delta.model_dump(),
                }
            )
        for old_cap_id, block in ctx.moved.values():
            for cap_id in (old_cap_id, block.capability_id):
                cap_levels.setdefault(cap_id, []).append("minor")
                cap_trigger.setdefault(cap_id, block)
            audit(db, actor, "move", f"block:{block.id}",
                  {"from_capability": old_cap_id, "to_capability": block.capability_id,
                   "cr_id": cr.id, "commit_id": commit.id})
        for block in [*ctx.archived.values(), *ctx.restored.values()]:
            cap_levels.setdefault(block.capability_id, []).append("minor")
            cap_trigger.setdefault(block.capability_id, block)
            audit(db, actor, "archive" if block.id in ctx.archived else "restore",
                  f"block:{block.id}", {"cr_id": cr.id, "commit_id": commit.id})
            if block.id in ctx.restored:
                events.emit(events.BLOCK_RESTORED, db, block, actor)
        db.flush()

        cap_versions = []
        for cap_id, levels in cap_levels.items():
            level = max(levels, key=lambda lv: LEVEL_RANK[lv])
            first = db.get(Capability, cap_id).current_version is None
            version = derive_capability_version(
                db, cap_trigger[cap_id], level, actor, note, cr_id=cr.id, commit_id=commit.id,
                capability_id=cap_id,
            )
            # 小业务级别只有 initial（首个版本）/ major / minor / patch
            reported = "initial" if first else ("minor" if level == "initial" else level)
            cap_versions.append({"capability_id": cap_id, "version": version, "level": reported})

        outcome = {
            "created": ctx.ref_info,
            "blocks": blocks_out,
            "archived_blocks": sorted(ctx.archived),
            "restored_blocks": sorted(ctx.restored),
            "moved_blocks": sorted(ctx.moved),
            "capability_versions": cap_versions,
        }
        commit.result_json = json.dumps(outcome, ensure_ascii=False)
        if dry_run:
            db.rollback()
        else:
            audit(db, actor, "commit", f"cr:{cr.id}/commit:{commit.id}",
                  {"seq": seq, "covers": covers, "blocks": [b["block_id"] for b in blocks_out]})
            db.commit()
        return commit, outcome
    except BaseException:
        db.rollback()
        raise
