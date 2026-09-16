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
- ``flatten_apis`` / ``delta`` / ``is_breaking``: recursive field-level diff —
  paths are dotted (e.g. ``response:GET /x:data.items.id: number``); added /
  removed / type-changed nested fields are detected; removed fields and type
  changes are breaking.
- ``apis_to_openapi``: recursively generates nested OpenAPI 3.x schemas.
- Versioning helpers: module semver + derived document semver.
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


def validate_rules(rules: object) -> list[dict]:
    """Validate and normalize a structured rule list. Returns normalized list."""
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise ApisValidationError("业务规则清单必须是数组")
    normalized = []
    for i, entry in enumerate(rules):
        where = f"第 {i + 1} 条规则"
        if not isinstance(entry, dict):
            raise ApisValidationError(f"{where} 必须是对象")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ApisValidationError(f"{where} 缺少规则名 name")
        detail = entry.get("detail")
        if not isinstance(detail, str) or not detail.strip():
            raise ApisValidationError(f"{where}（{name.strip()}）缺少规则详述 detail")
        normalized.append({"name": name.strip(), "detail": detail.strip()})
    return normalized


def rules_delta(old_rules: list, new_rules: list) -> dict[str, list[str]]:
    """规则清单 delta：按 rule name 匹配，detail 变了算 modified。
    rules 变化不算破坏性（is_breaking 只看 apis 侧的 added/modified/removed）。"""
    old = {r["name"]: r.get("detail", "") for r in validate_rules(old_rules)}
    new = {r["name"]: r.get("detail", "") for r in validate_rules(new_rules)}
    return {
        "rules_added": sorted(new.keys() - old.keys()),
        "rules_removed": sorted(old.keys() - new.keys()),
        "rules_modified": sorted(
            name for name in old.keys() & new.keys() if old[name] != new[name]
        ),
    }


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


def is_breaking(d: dict[str, list[str]]) -> bool:
    """破坏性判定：
    - 删除整个 API、删除必填字段、任何类型/必填标志变更（modified）→ 破坏性；
    - 删除可选字段（required=false）→ 非破坏性（客户端本就不依赖它），
      这是演练确认的细化规则：仅删可选字段可走 fastTrack。
    """
    if d["modified"]:
        return True
    for entry in d["removed"]:
        if entry.startswith("api:"):
            return True
        if entry.rstrip().endswith("required"):
            return True
    return False


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


def bump_level(d: dict[str, list[str]]) -> str:
    """major | minor | patch for a non-first publish."""
    if is_breaking(d):
        return "major"
    if d["added"]:
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
    """First publish is 1.0.0 (level 'initial'); then breaking -> MAJOR,
    additions -> MINOR, anything else -> PATCH. Returns (version, level)."""
    if current is None:
        return INITIAL_VERSION, "initial"
    level = bump_level(d)
    return bump_version(current, level), level


def derive_document_version(current: str | None, module_level: str) -> str:
    """文档版本是模块发布的派生物：任一模块 MAJOR -> 文档 MAJOR；否则任一
    模块 MINOR（含模块首次发布）-> 文档 MINOR；否则 PATCH。首个文档版本 1.0.0。"""
    if current is None:
        return INITIAL_VERSION
    level = "minor" if module_level == "initial" else module_level
    return bump_version(current, level)
