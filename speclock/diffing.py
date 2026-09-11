"""Structured-API validation, diffing and OpenAPI generation.

The source of truth for a module's API section is a structured list
(``apis_json``)::

    [{"name": "拉取日报主表", "api": "GET /api/daily-report",
      "request":  [{"name": "date", "type": "string", "required": true, "desc": "查询日期"}],
      "response": [{"name": "sales", "type": "number", "required": true, "desc": "销售额"}]}]

- ``validate_apis``: structural validation (api name must parse to
  METHOD + /path; field name non-empty; type in enum). Invalid modules
  cannot be saved or published.
- ``flatten_apis`` / ``delta`` / ``is_breaking``: field-level diff —
  added/removed request & response fields and type (or required-flag)
  changes are detected; removed fields and type changes are breaking.
- ``apis_to_openapi``: generates the OpenAPI 3.x document stored on each
  BlockVersion for machine consumers.
- Versioning helpers: module semver + derived document semver.
"""

from __future__ import annotations

import difflib

import yaml

FIELD_TYPES = ("string", "number", "integer", "boolean", "array", "object")
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
    return {
        "name": name.strip(),
        "type": ftype,
        "required": bool(field.get("required", False)),
        "desc": str(field.get("desc", "") or ""),
    }


def validate_apis(apis: object) -> list[dict]:
    """Validate and normalize a structured API list. Returns normalized list."""
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
        method, path = parse_api_name(entry.get("api", ""))
        normalized.append(
            {
                "name": name.strip(),
                "api": f"{method} {path}",
                "request": [
                    _validate_field(f, f"{where} 请求体") for f in entry.get("request") or []
                ],
                "response": [
                    _validate_field(f, f"{where} 响应体") for f in entry.get("response") or []
                ],
            }
        )
    return normalized


def flatten_apis(apis: list) -> dict[str, str]:
    """Flatten to {dotted.path: descriptor} for field-level diffing.

    Display names are deliberately excluded (文案改动不算契约变更)。
    """
    flat: dict[str, str] = {}
    for entry in validate_apis(apis):
        method, path = parse_api_name(entry["api"])
        key = f"{method} {path}"
        flat[f"api:{key}"] = "operation"
        for kind in ("request", "response"):
            for f in entry[kind]:
                suffix = f"{f['type']}{' required' if f['required'] else ''}"
                flat[f"{kind}:{key}:{f['name']}"] = suffix
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
    """Removed APIs/fields or type/required changes are breaking for consumers."""
    return bool(d["removed"] or d["modified"])


def _fields_to_schema(fields: list[dict]) -> dict:
    props: dict[str, dict] = {}
    required: list[str] = []
    for f in fields:
        prop: dict = {"type": f["type"]}
        if f.get("desc"):
            prop["description"] = f["desc"]
        props[f["name"]] = prop
        if f.get("required"):
            required.append(f["name"])
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def apis_to_openapi(apis: list) -> dict:
    """Generate an OpenAPI 3.x document from the structured API list."""
    paths: dict[str, dict] = {}
    for entry in validate_apis(apis):
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
