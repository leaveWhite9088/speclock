"""对外接口的契约：整份 OpenAPI 和 docs/openapi.json 逐字比对。

形状变了（路径、方法、参数、响应字段、错误结构……）这里就会失败。**有意**改接口时：

    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_contract.py

重新生成快照，把 docs/openapi.json 的变化一起提交，并在 docs/CHANGELOG.md 记一条
（外部集成方靠这份文件和 CHANGELOG 知道接口变了什么）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from speclock_server.main import create_app

SNAPSHOT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"

# 成功响应不是 JSON 的接口（目前没有；有的话在这里登记并写理由）
NO_JSON_RESPONSE: set[tuple[str, str]] = set()


def current_spec() -> dict:
    spec = json.loads(json.dumps(create_app().openapi()))
    spec["info"].pop("version", None)  # 版本号单独由 test_architecture 管，不让每次升版本都改快照
    return spec


def dump(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_openapi_matches_the_committed_snapshot():
    text = dump(current_spec())
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT"):
        SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
    assert SNAPSHOT.is_file(), "docs/openapi.json 不存在：UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_contract.py"
    expected = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    if text != expected:
        old, new = json.loads(expected), json.loads(text)
        added = sorted(set(new["paths"]) - set(old["paths"]))
        removed = sorted(set(old["paths"]) - set(new["paths"]))
        changed = sorted(p for p in set(old["paths"]) & set(new["paths"]) if old["paths"][p] != new["paths"][p])
        old_s, new_s = old["components"]["schemas"], new["components"]["schemas"]
        schemas = sorted(s for s in set(old_s) | set(new_s) if old_s.get(s) != new_s.get(s))
        raise AssertionError(
            "对外接口的形状变了，和 docs/openapi.json 不一致。\n"
            f"  新增路径：{added}\n  删除路径：{removed}\n  变化的路径：{changed}\n  变化的模型：{schemas}\n"
            "如果这是有意的：UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_contract.py，"
            "提交 docs/openapi.json，并在 docs/CHANGELOG.md 记一条。"
        )


def test_every_api_operation_declares_a_json_response():
    """新增接口必须声明响应模型：成功响应要有 JSON schema，否则接口文档里没有返回结构。"""
    missing = []
    for path, ops in current_spec()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, op in ops.items():
            if (method.upper(), path) in NO_JSON_RESPONSE:
                continue
            ok = [code for code in op["responses"] if code.startswith("2")]
            content = op["responses"][ok[0]].get("content", {}) if ok else {}
            if not content.get("application/json", {}).get("schema"):
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"这些接口没有声明响应模型（用 response_model=...，模型放在 speclock_server/responses.py）：{missing}"


def test_authenticated_operations_document_the_error_shape():
    """需要 key 的接口都声明了统一的错误结构 {detail, code}。"""
    spec = current_spec()
    err = spec["components"]["schemas"]["ErrorOut"]
    assert set(err["required"]) == {"detail", "code"}
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/") or path == "/api/v1/health":
            continue
        for method, op in ops.items():
            for status in ("401", "403", "404", "409", "422"):
                ref = op["responses"][status]["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorOut"), (method, path, status)
