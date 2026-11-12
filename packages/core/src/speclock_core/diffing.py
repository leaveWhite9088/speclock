"""Structured-API validation, diffing and OpenAPI generation.

The source of truth for a module's API section is a structured list
(``apis_json``) with a RECURSIVE field model::

    [{"name": "拉取日报主表", "api": "GET /api/daily-report",
      "desc": "前端日报页调用，只读无副作用",  # 端点语义，写入口径必填
      "request":  [{"name": "date", "type": "string", "required": true,
                    "description": "查询日期", "children": []}],
      "response": [{"name": "data", "type": "object", "required": true,
                    "description": "", "children": [
                        {"name": "items", "type": "array", "required": true,
                         "description": "", "children": [
                             {"name": "id", "type": "integer", ...}]}]}]}]

- ``children`` is only allowed under ``object`` / ``array`` types (for array it
  describes the element structure). Nesting depth is not artificially limited.
- ``flatten_apis`` / ``delta`` / ``has_api_removal_or_change``: recursive field-level diff —
  paths are dotted (e.g. ``response:GET /x:data.items.id: number``); added /
  removed / type-changed nested fields are detected; any removal and any
  type / required-flag change counts as a MAJOR-level change.
- ``apis_to_openapi``: recursively generates nested OpenAPI 3.x schemas.
- Versioning helpers: module semver + derived capability semver.
"""

from __future__ import annotations

import difflib

import yaml

FIELD_TYPES = ("string", "number", "integer", "boolean", "array", "object")
CONTAINER_TYPES = ("object", "array")
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")


class ApisValidationError(ValueError):
    pass


def parse_api_name(api: str) -> tuple[str, str]:
    """'GET /api/daily-report' -> ('GET', '/api/daily-report')."""
    if not isinstance(api, str):
        raise ApisValidationError("API 名必须是字符串，如 'GET /api/daily-report'")
    parts = api.strip().split(None, 1)
    if len(parts) != 2:
        raise ApisValidationError(f"API 名必须形如 '方法 路径'，got {api!r}")
    method, path = parts[0].upper(), parts[1].strip()
    if method not in HTTP_METHODS:
        raise ApisValidationError(f"HTTP 方法必须是 {HTTP_METHODS} 之一，got {method!r}")
    if not path.startswith("/"):
        raise ApisValidationError(f"路径必须以 / 开头，got {path!r}")
    return method, path


def _validate_field(field: object, where: str) -> dict:
    if not isinstance(field, dict):
        raise ApisValidationError(f"{where} 的字段行必须是对象")
    name = field.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApisValidationError(f"{where} 存在字段名为空的行")
    ftype = field.get("type")
    if ftype not in FIELD_TYPES:
        raise ApisValidationError(
            f"{where} 字段 {name!r} 的类型必须是 {FIELD_TYPES} 之一，got {ftype!r}"
        )
    children = field.get("children") or []
    if not isinstance(children, list):
        raise ApisValidationError(f"{where} 字段 {name!r} 的 children 必须是数组")
    # 空 children 视为无 children（GET→PUT 往返会带上空 children，不应报错）；
    # 仅当标量带非空 children 才拒绝。
    if children and ftype not in CONTAINER_TYPES:
        raise ApisValidationError(
            f"{where} 字段 {name!r} 是 {ftype} 类型，不允许有子字段"
            f"（children 只可用于 object/array）"
        )
    if ftype not in CONTAINER_TYPES:
        children = []
    fwhere = f"{where}.{name}"
    return {
        "name": name.strip(),
        "type": ftype,
        "required": bool(field.get("required", False)),
        "description": str(field.get("description", "") or ""),
        "children": [_validate_field(c, fwhere) for c in children],
    }


def validate_apis(apis: object, require_desc: bool = True) -> list[dict]:
    """Validate and normalize a structured API list. Returns normalized list.

    ``require_desc=True``（写入口径：保存/发布/提案）要求每条 API 带非空
    ``desc``（端点语义）；diff/OpenAPI 生成等读取存量快照的场景传 False，
    兼容历史版本里还没有 desc 的数据。
    """
    if apis is None:
        return []
    if not isinstance(apis, list):
        raise ApisValidationError("API 列表必须是数组")
    normalized = []
    for i, entry in enumerate(apis):
        where = f"第 {i + 1} 个 API"
        if not isinstance(entry, dict):
            raise ApisValidationError(f"{where} 必须是对象")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ApisValidationError(f"{where} 缺少名称（中文显示名）")
        desc = str(entry.get("desc", "") or "")
        if require_desc and not desc.strip():
            raise ApisValidationError(
                f"{where}（{name.strip()}）缺少端点语义描述 desc"
                f"（谁调用、为什么、副作用/幂等等字段表看不出来的信息）"
            )
        method, path = parse_api_name(entry.get("api", ""))
        normalized.append(
            {
                "name": name.strip(),
                "api": f"{method} {path}",
                "desc": desc.strip(),
                "request": [
                    _validate_field(f, f"{where} 请求体") for f in entry.get("request") or []
                ],
                "response": [
                    _validate_field(f, f"{where} 响应体") for f in entry.get("response") or []
                ],
            }
        )
    return normalized


ITEM_KINDS = {
    # kind -> (id 前缀, 中文名)
    "rules": ("R", "规则"),
    "acceptance": ("AC", "验收条件"),
}


def _item_id_no(item_id: str, prefix: str) -> int | None:
    """'R-12' -> 12；格式不符返回 None。"""
    head, _, tail = str(item_id or "").partition("-")
    if head != prefix or not tail.isdigit():
        return None
    return int(tail)


def validate_items(items: object, kind: str) -> list[dict]:
    """校验并规范化带稳定 ID 的条目清单（规则 / 验收条件同构）：
    [{id, name, detail}]。id 可缺省（由服务端分配），给了就必须形如 R-1 / AC-1
    且在清单内唯一。"""
    prefix, label = ITEM_KINDS[kind]
    if items is None:
        return []
    if not isinstance(items, list):
        raise ApisValidationError(f"{label}清单必须是数组")
    normalized = []
    seen: set[str] = set()
    for i, entry in enumerate(items):
        where = f"第 {i + 1} 条{label}"
        if not isinstance(entry, dict):
            raise ApisValidationError(f"{where} 必须是对象")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ApisValidationError(f"{where} 缺少名称 name")
        detail = entry.get("detail")
        if not isinstance(detail, str) or not detail.strip():
            raise ApisValidationError(f"{where}（{name.strip()}）缺少详述 detail")
        item_id = str(entry.get("id") or "").strip()
        if item_id:
            if _item_id_no(item_id, prefix) is None:
                raise ApisValidationError(
                    f"{where}（{name.strip()}）的 id {item_id!r} 不合法，应形如 {prefix}-1"
                )
            if item_id in seen:
                raise ApisValidationError(f"{label} id {item_id} 重复")
            seen.add(item_id)
        normalized.append({"id": item_id, "name": name.strip(), "detail": detail.strip()})
    return normalized


def validate_rules(rules: object) -> list[dict]:
    """Validate and normalize a structured rule list. Returns normalized list."""
    return validate_items(rules, "rules")


def validate_acceptance(items: object) -> list[dict]:
    """Validate and normalize a structured acceptance-criteria list."""
    return validate_items(items, "acceptance")


def taken_item_numbers(kind: str, *lists: list) -> set[int]:
    """从若干条目清单里收集已用过的编号（草稿 + 全部历史快照），分配新 id 时
    取其最大值 + 1，保证编号不复用（即使旧条目已被删除）。"""
    prefix, _ = ITEM_KINDS[kind]
    nums: set[int] = set()
    for items in lists:
        for entry in items or []:
            n = _item_id_no(entry.get("id", ""), prefix) if isinstance(entry, dict) else None
            if n is not None:
                nums.add(n)
    return nums


def assign_item_ids(items: list[dict], kind: str, taken: set[int] | None = None) -> list[dict]:
    """给缺 id 的条目按出现顺序分配新 id（R-n / AC-n），返回新列表。
    taken 是已用编号集合（含历史快照），新编号从其最大值 + 1 起。"""
    prefix, _ = ITEM_KINDS[kind]
    used = set(taken or set()) | taken_item_numbers(kind, items)
    nxt = max(used, default=0) + 1
    out = []
    for entry in items:
        entry = dict(entry)
        if not entry.get("id"):
            entry["id"] = f"{prefix}-{nxt}"
            nxt += 1
        out.append(entry)
    return out


def items_delta(old_items: list, new_items: list, kind: str) -> dict[str, list[str]]:
    """条目清单 delta：按 id 匹配（老快照无 id 时退回按名称）。
    - modified：详述（detail）变了；
    - renamed：只有名称变了、详述没变（名称只是标签，不算业务变更）；
    条目形如 'R-1 销售额口径'。键：{kind}_added / _removed / _modified / _renamed。"""
    def key(e: dict) -> str:
        return e.get("id") or e["name"]

    old = {key(e): e for e in validate_items(old_items, kind)}
    new = {key(e): e for e in validate_items(new_items, kind)}

    def label(e: dict) -> str:
        return f"{e['id']} {e['name']}" if e.get("id") else e["name"]

    modified, renamed = [], []
    for k in old.keys() & new.keys():
        o, n = old[k], new[k]
        if o["detail"] != n["detail"]:
            modified.append(label(n))
        elif o["name"] != n["name"]:
            renamed.append(label(n))
    return {
        f"{kind}_added": sorted(label(new[k]) for k in new.keys() - old.keys()),
        f"{kind}_removed": sorted(label(old[k]) for k in old.keys() - new.keys()),
        f"{kind}_modified": sorted(modified),
        f"{kind}_renamed": sorted(renamed),
    }


def rules_delta(old_rules: list, new_rules: list) -> dict[str, list[str]]:
    return items_delta(old_rules, new_rules, "rules")


def acceptance_delta(old_items: list, new_items: list) -> dict[str, list[str]]:
    return items_delta(old_items, new_items, "acceptance")


def _flatten_fields(flat: dict[str, str], key: str, prefix: str, fields: list[dict]) -> None:
    for f in fields:
        path = f"{prefix}{f['name']}"
        flat[f"{key}:{path}"] = f"{f['type']}{' required' if f['required'] else ''}"
        if f["children"]:
            _flatten_fields(flat, key, path + ".", f["children"])


def flatten_apis(apis: list) -> dict[str, str]:
    """Recursively flatten to {dotted.path: descriptor} for field-level diffing.

    Display names and descriptions are deliberately excluded (文案改动不算契约变更)。
    """
    flat: dict[str, str] = {}
    for entry in validate_apis(apis, require_desc=False):
        method, path = parse_api_name(entry["api"])
        key_prefix = f"{method} {path}"
        flat[f"api:{key_prefix}"] = "operation"
        for kind in ("request", "response"):
            _flatten_fields(flat, f"{kind}:{key_prefix}", "", entry[kind])
    return flat


def delta(old_apis: list, new_apis: list) -> dict[str, list[str]]:
    """Field-level {added, modified, removed} between two API lists."""
    old = flatten_apis(old_apis)
    new = flatten_apis(new_apis)
    added = sorted(f"{k}: {new[k]}" for k in new.keys() - old.keys())
    removed = sorted(f"{k}: {old[k]}" for k in old.keys() - new.keys())
    modified = sorted(
        f"{k}: {old[k]} -> {new[k]}"
        for k in old.keys() & new.keys()
        if old[k] != new[k]
    )
    return {"added": added, "modified": modified, "removed": removed}


def changed_api_keys(old_apis: list, new_apis: list) -> set[str]:
    """两个 API 列表之间发生过变化的 API 标识集合（'METHOD /path'）。

    基于 flatten 键集合：新增/删除/字段值变化的条目都映射回所属 API。
    delta 提案的 stale 检查用它判定「基底版本之后动过哪些 API」。
    """
    old = flatten_apis(old_apis)
    new = flatten_apis(new_apis)
    keys = (old.keys() ^ new.keys()) | {
        k for k in old.keys() & new.keys() if old[k] != new[k]
    }
    out: set[str] = set()
    for k in keys:
        _, rest = k.split(":", 1)
        out.add(rest.split(":", 1)[0] if ":" in rest else rest)
    return out


def has_api_removal_or_change(d: dict[str, list[str]]) -> bool:
    """API 侧是否有删除（整个 API / 任何字段，含可选字段）或修改（类型 / 必填
    标志变更）。只有新增不算。仅用于版本级别标签，不再有任何发布闸门。"""
    return bool(d.get("modified") or d.get("removed"))


def _field_to_schema(f: dict) -> dict:
    schema: dict = {"type": f["type"]}
    if f.get("description"):
        schema["description"] = f["description"]
    children = f.get("children") or []
    if f["type"] == "object":
        props, required = _children_to_properties(children)
        schema["properties"] = props
        if required:
            schema["required"] = required
    elif f["type"] == "array":
        if children:
            props, required = _children_to_properties(children)
            items: dict = {"type": "object", "properties": props}
            if required:
                items["required"] = required
            schema["items"] = items
        else:
            schema["items"] = {}
    return schema


def _children_to_properties(children: list[dict]) -> tuple[dict, list[str]]:
    props: dict[str, dict] = {}
    required: list[str] = []
    for f in children:
        props[f["name"]] = _field_to_schema(f)
        if f.get("required"):
            required.append(f["name"])
    return props, required


def _fields_to_schema(fields: list[dict]) -> dict:
    props, required = _children_to_properties(fields)
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def apis_to_openapi(apis: list) -> dict:
    """Generate an OpenAPI 3.x document from the structured API list."""
    paths: dict[str, dict] = {}
    for entry in validate_apis(apis, require_desc=False):
        method, path = parse_api_name(entry["api"])
        operation: dict = {
            "summary": entry["name"],
            "responses": {
                "200": {
                    "description": entry["name"],
                    "content": {
                        "application/json": {"schema": _fields_to_schema(entry["response"])}
                    },
                }
            },
        }
        if entry["request"]:
            operation["requestBody"] = {
                "content": {"application/json": {"schema": _fields_to_schema(entry["request"])}}
            }
        paths.setdefault(path, {})[method.lower()] = operation
    return {
        "openapi": "3.0.3",
        "info": {"title": "SpecLock generated", "version": "1.0.0"},
        "paths": paths,
    }


def apis_to_openapi_yaml(apis: list) -> str:
    return yaml.safe_dump(apis_to_openapi(apis), allow_unicode=True, sort_keys=False)


# ---------- delta 结构化分组（diff 页用） ----------


def field_lookup(apis: list) -> dict[tuple[str, str, str], dict]:
    """(kind, 'METHOD /path', dotted.field.path) -> field dict，供 diff 页查说明。"""

    def walk(out: dict, kind: str, api: str, prefix: str, fields: list[dict]) -> None:
        for f in fields:
            path = prefix + f["name"]
            out[(kind, api, path)] = f
            if f.get("children"):
                walk(out, kind, api, path + ".", f["children"])

    out: dict = {}
    for entry in validate_apis(apis, require_desc=False):
        for kind in ("request", "response"):
            walk(out, kind, entry["api"], "", entry[kind])
    return out


def _parse_delta_key(key: str) -> tuple[str, str, str]:
    """'response:GET /x:rule.scope.store_name' -> ('response', 'GET /x', 'rule.scope.store_name')
    'api:GET /x' -> ('api', 'GET /x', '')"""
    kind, rest = key.split(":", 1)
    if ":" not in rest:
        return kind, rest, ""
    method, remainder = rest.split(" ", 1)
    path, fieldpath = remainder.split(":", 1)
    return kind, f"{method} {path}", fieldpath


def group_delta(
    d: dict[str, list[str]], old_apis: list, new_apis: list
) -> list[dict]:
    """把 {added, modified, removed} 字符串 delta 按 API 分组为结构化行：
    [{api_key, api_name, changes: [{kind, scope, path, detail, description}]}]"""
    old_lookup = field_lookup(old_apis)
    new_lookup = field_lookup(new_apis)
    api_names: dict[str, str] = {}
    for apis in (new_apis, old_apis):
        for entry in apis:
            api_names.setdefault(entry["api"], entry["name"])

    groups: dict[str, dict] = {}

    def group_for(api_key: str) -> dict:
        if api_key not in groups:
            groups[api_key] = {
                "api_key": api_key,
                "api_name": api_names.get(api_key, ""),
                "changes": [],
            }
        return groups[api_key]

    def add(kind: str, entry: str) -> None:
        # entry 形如 "response:GET /x:a.b: string required" 或修改 "…: old -> new"
        colon = entry.find(": ")
        key, detail = entry[:colon], entry[colon + 2:]
        scope, api_key, fieldpath = _parse_delta_key(key)
        if kind == "added":
            f = new_lookup.get((scope, api_key, fieldpath))
        elif kind == "removed":
            f = old_lookup.get((scope, api_key, fieldpath))
        else:
            f = new_lookup.get((scope, api_key, fieldpath)) or old_lookup.get(
                (scope, api_key, fieldpath)
            )
        group_for(api_key)["changes"].append(
            {
                "kind": kind,
                "scope": scope,  # api|request|response
                "path": fieldpath,
                "detail": detail,
                "description": (f or {}).get("description", ""),
            }
        )

    for kind in ("added", "modified", "removed"):
        for entry in d[kind]:
            add(kind, entry)
    return list(groups.values())


def text_diff(old: str, new: str, fromfile: str = "old", tofile: str = "new") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


# ---------- versioning ----------

INITIAL_VERSION = "1.0.0"


def semver_key(v: str) -> tuple[int, int, int]:
    """'1.2.0' -> (1, 2, 0)，供按语义版本排序/取最大。"""
    return tuple(int(part) for part in v.split("."))


def bump_level(d: dict[str, list[str]]) -> str:
    """版本级别标签（major | minor | patch），完全由结构化 diff 机械算出，
    不依赖任何人或 Agent 的判断。它是给外部 Agent 的参考，Core 不规定它们
    据此该做什么：

    - MAJOR：有任何删除或修改——API（删 API / 字段、类型或必填标志变更）、
      规则、验收条件；
    - MINOR：只有新增（API、字段、规则、验收条件）；
    - PATCH：其余（只改背景、API 的文字说明、条目仅改名等）。

    规则与验收条件是自然语言，机器分不清「改措辞」与「改语义」，因此按保守
    一侧归类：标得偏重只是让下游多核对一次，标得偏轻却可能掩盖不兼容变更。
    条目只改名称（详述不变）算 renamed，不影响级别。
    """
    def has(*keys: str) -> bool:
        return any(d.get(k) for k in keys)

    if has_api_removal_or_change(d) or has(
        "rules_removed", "rules_modified", "acceptance_removed", "acceptance_modified",
    ):
        return "major"
    if has("added", "rules_added", "acceptance_added"):
        return "minor"
    return "patch"


def bump_version(current: str, level: str) -> str:
    major, minor, patch = (int(part) for part in current.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def next_module_version(current: str | None, d: dict[str, list[str]]) -> tuple[str, str]:
    """First publish is 1.0.0 (level 'initial'); then any removal/modification -> MAJOR,
    additions -> MINOR, anything else -> PATCH. Returns (version, level)."""
    if current is None:
        return INITIAL_VERSION, "initial"
    level = bump_level(d)
    return bump_version(current, level), level


def derive_capability_version(current: str | None, module_level: str) -> str:
    """小业务版本是模块发布的派生物：任一模块 MAJOR -> 文档 MAJOR；否则任一
    模块 MINOR（含模块首次发布）-> 文档 MINOR；否则 PATCH。首个小业务版本 1.0.0。"""
    if current is None:
        return INITIAL_VERSION
    level = "minor" if module_level == "initial" else module_level
    return bump_version(current, level)
