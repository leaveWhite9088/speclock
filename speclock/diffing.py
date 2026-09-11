"""Diffing utilities.

- ``validate_openapi_fragment``: minimal structural check that a block's API
  section is a legal OpenAPI 3.x YAML fragment (MVP deliberately avoids heavy
  validators; the meeting decision was "哪怕错的标准也比没有标准强").
- ``flatten_openapi``: field-level view of a fragment — operations and schema
  property types keyed by dotted path.
- ``delta``: {added, modified, removed} between two fragments.
- ``is_breaking``: removed fields or type changes are breaking and force the
  human-confirm (non-fastTrack) publish channel.
- ``text_diff``: unified diff for the Markdown sections.
- ``next_version``: semver bump derived from the delta.
"""

from __future__ import annotations

import difflib

import yaml


class OpenAPIValidationError(ValueError):
    pass


def validate_openapi_fragment(yaml_text: str) -> dict:
    """Parse and structurally validate an OpenAPI 3.x YAML fragment.

    An empty fragment is valid (block has no API section). Returns the parsed
    mapping. Raises OpenAPIValidationError otherwise.
    """
    if not yaml_text or not yaml_text.strip():
        return {}
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise OpenAPIValidationError(f"invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise OpenAPIValidationError("API section must be a YAML mapping")
    if "openapi" in doc:
        version = str(doc["openapi"])
        if not version.startswith("3."):
            raise OpenAPIValidationError(f"openapi version must be 3.x, got {version!r}")
    if "paths" in doc and not isinstance(doc["paths"], dict):
        raise OpenAPIValidationError("'paths' must be a mapping")
    if "components" in doc and not isinstance(doc["components"], dict):
        raise OpenAPIValidationError("'components' must be a mapping")
    schemas = (doc.get("components") or {}).get("schemas")
    if schemas is not None and not isinstance(schemas, dict):
        raise OpenAPIValidationError("'components.schemas' must be a mapping")
    if not (doc.get("paths") or schemas):
        raise OpenAPIValidationError(
            "fragment must declare at least one path or component schema"
        )
    return doc


def flatten_openapi(yaml_text: str) -> dict[str, str]:
    """Flatten a fragment to {dotted.field.path: descriptor}.

    Operations appear as ``op:GET /daily/report``; schema properties as
    ``prop:DailyReport.sales: number``. Only structure that matters for a
    consumer contract is flattened.
    """
    doc = validate_openapi_fragment(yaml_text)
    flat: dict[str, str] = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            flat[f"op:{method.upper()} {path}"] = "operation"
            if isinstance(op, dict):
                for param in op.get("parameters") or []:
                    if isinstance(param, dict) and "name" in param:
                        ptype = ((param.get("schema") or {}).get("type")) or "any"
                        flat[f"param:{method.upper()} {path}:{param['name']}"] = str(ptype)
    for schema_name, schema in ((doc.get("components") or {}).get("schemas") or {}).items():
        if not isinstance(schema, dict):
            continue
        for prop_name, prop in (schema.get("properties") or {}).items():
            ptype = (prop or {}).get("type", "any") if isinstance(prop, dict) else "any"
            flat[f"prop:{schema_name}.{prop_name}"] = str(ptype)
        for req in schema.get("required") or []:
            flat[f"required:{schema_name}.{req}"] = "required"
    return flat


def delta(old_yaml: str, new_yaml: str) -> dict[str, list[str]]:
    """Field-level {added, modified, removed} between two fragments."""
    old = flatten_openapi(old_yaml)
    new = flatten_openapi(new_yaml)
    added = sorted(f"{k}: {new[k]}" for k in new.keys() - old.keys())
    removed = sorted(f"{k}: {old[k]}" for k in old.keys() - new.keys())
    modified = sorted(
        f"{k}: {old[k]} -> {new[k]}"
        for k in old.keys() & new.keys()
        if old[k] != new[k]
    )
    return {"added": added, "modified": modified, "removed": removed}


def is_breaking(d: dict[str, list[str]]) -> bool:
    """Removed fields/paths or type changes are breaking for consumers."""
    return bool(d["removed"] or d["modified"])


def text_diff(old: str, new: str, fromfile: str = "old", tofile: str = "new") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def next_version(current: str | None, d: dict[str, list[str]]) -> str:
    """First publish is 1.0.0; then breaking -> MAJOR, additions -> MINOR,
    anything else -> PATCH."""
    if current is None:
        return "1.0.0"
    major, minor, patch = (int(part) for part in current.split("."))
    if is_breaking(d):
        return f"{major + 1}.0.0"
    if d["added"]:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
