"""MCP 工具的契约：每个工具的名字、参数、它调用的 REST 接口、以及返回的结构，和 docs/mcp_tools.json 逐字比对。

MCP 工具返回的是**文本**：``{"status": <HTTP 状态码>, "body": <REST 响应>}``（或 ``{"error": ...}``）。
``body`` 就是对应 REST 接口的响应，所以返回结构直接引用 OpenAPI 里那个接口的响应模型（见快照的 ``returns``），
不另写一份。工具的描述文字（给模型看的提示词）不在快照里——改措辞不算接口变化。

有意改工具（名字、参数、调用的接口、返回结构）时：

    UPDATE_MCP_SNAPSHOT=1 uv run pytest tests/test_mcp_contract.py

重新生成快照，提交 docs/mcp_tools.json，并在 docs/CHANGELOG.md 记一条。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from speclock_mcp import server as mcp_server
from speclock_server.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs" / "mcp_tools.json"

ENVELOPE = {
    "ok": {"status": "HTTP 状态码（int）", "body": "REST 响应；形状见各工具的 returns"},
    "not_reached": {"error": "服务连不上 / 没配置 key 等，文本"},
}

# 工具返回和「REST 响应原样包一层」不一样的地方（不在这里写的工具 = 原样）
RETURN_NOTES = {
    "whoami": "body 是 /me 的响应，另外多一个 key_source（这把 key 从哪来的，只有 MCP 有）",
    "use_api_key": '成功：{"switched": true, "identity": <GET /me 的响应>}；失败：{"error", "detail"}，不是 status/body 包装',
    "create_change_request": "服务端比客户端旧、认不出 kind 时返回 {error, created}，不是 status/body 包装",
    "update_change_request": "同 create_change_request",
}

# 没有必填参数、但不给就不会去调 REST 的工具
EXTRA_ARGS = {"use_api_key": {"key": "x"}}

SAMPLE = {"integer": 1, "string": "x", "boolean": False, "array": [], "object": {}, "number": 1}


def _sample_args(schema: dict) -> dict:
    args = {}
    for name in schema.get("required", []):
        prop = schema["properties"][name]
        kind = prop.get("type") or next(
            (a["type"] for a in prop.get("anyOf", []) if a.get("type") != "null"), "string")
        args[name] = SAMPLE[kind]
    return args


def _openapi_op(spec: dict, method: str, path: str) -> tuple[str, dict]:
    for template, ops in spec["paths"].items():
        if method.lower() in ops and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path):
            return template, ops[method.lower()]
    raise AssertionError(f"{method} {path} 不在 OpenAPI 里：MCP 工具调用了不存在的 REST 接口")


def _returns(op: dict) -> dict:
    ok = next(code for code in op["responses"] if code.startswith("2"))
    return op["responses"][ok]["content"]["application/json"]["schema"]


def build_contract(monkeypatch) -> dict:
    spec = json.loads(json.dumps(create_app().openapi()))
    calls: list[tuple[str, str]] = []

    def fake_call(method, path, **kwargs):
        calls.append((method, path))
        return json.dumps({"status": 200, "body": {}})

    monkeypatch.setattr(mcp_server, "_call", fake_call)
    monkeypatch.setattr(mcp_server, "AGENT_KEY", "k")  # use_api_key 会改这两个全局，测完还原
    monkeypatch.setattr(mcp_server, "KEY_SOURCE", "t")
    tools = {}
    for tool in sorted(mcp_server.mcp._tool_manager.list_tools(), key=lambda t: t.name):
        calls.clear()
        args = _sample_args(tool.parameters) | EXTRA_ARGS.get(tool.name, {})
        getattr(mcp_server, tool.name)(**args)
        assert calls, f"工具 {tool.name} 没有调用任何 REST 接口"
        method, path = calls[0]
        template, op = _openapi_op(spec, method, path)
        tools[tool.name] = {
            "params": tool.parameters,
            "rest": f"{method} {template}",
            "returns": _returns(op),
        }
        if tool.name in RETURN_NOTES:
            tools[tool.name]["return_note"] = RETURN_NOTES[tool.name]
    assert set(RETURN_NOTES) <= set(tools), "RETURN_NOTES 里有不存在的工具"
    return {"envelope": ENVELOPE, "tools": tools}


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_mcp_tools_match_the_committed_snapshot(monkeypatch):
    text = dump(build_contract(monkeypatch))
    if os.environ.get("UPDATE_MCP_SNAPSHOT"):
        SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
    assert SNAPSHOT.is_file(), "docs/mcp_tools.json 不存在：UPDATE_MCP_SNAPSHOT=1 uv run pytest tests/test_mcp_contract.py"
    expected = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    if text != expected:
        old, new = json.loads(expected)["tools"], json.loads(text)["tools"]
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = sorted(t for t in set(old) & set(new) if old[t] != new[t])
        raise AssertionError(
            "MCP 工具的契约变了，和 docs/mcp_tools.json 不一致。\n"
            f"  新增工具：{added}\n  删除工具：{removed}\n  变化的工具（参数 / 调用的接口 / 返回结构）：{changed}\n"
            "如果这是有意的：UPDATE_MCP_SNAPSHOT=1 uv run pytest tests/test_mcp_contract.py，"
            "提交 docs/mcp_tools.json，并在 docs/CHANGELOG.md 记一条。"
        )


def test_every_tool_declares_a_return_structure(monkeypatch):
    for name, tool in build_contract(monkeypatch)["tools"].items():
        assert tool["returns"], name


def test_tool_output_is_the_documented_envelope(env, monkeypatch):
    """真实调用几个工具：返回是 {"status", "body"}，body 的键和 REST 响应声明的一致。"""
    c = env["client"]
    monkeypatch.setattr(mcp_server.httpx, "request", lambda method, url, headers=None, timeout=None, **kw:
                        c.request(method, url.removeprefix(mcp_server.BASE_URL), headers=headers, **kw))
    admin = env["human"]["X-API-Key"]
    monkeypatch.setattr(mcp_server, "AGENT_KEY", admin)
    monkeypatch.setattr(mcp_server, "KEY_SOURCE", "t")
    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]

    out = json.loads(mcp_server.whoami())
    assert set(out) == {"status", "body"} and out["status"] == 200
    assert set(out["body"]) == set(schemas["MeOut"]["properties"]) | {"key_source"}

    out = json.loads(mcp_server.list_projects())
    assert set(out) == {"status", "body"}
    assert all(set(p) == set(schemas["ProjectOut"]["properties"]) for p in out["body"])

    out = json.loads(mcp_server.get_index())
    assert out["status"] == 200 and isinstance(out["body"], list)

    out = json.loads(mcp_server.get_activity(limit=3))
    assert all(set(r) == set(schemas["ActivityOut"]["properties"]) for r in out["body"])

    out = json.loads(mcp_server.get_change_request(9999))  # 错误也是同一层包装，body 是 {detail, code}
    assert out["status"] == 404 and set(out["body"]) == {"detail", "code"}


@pytest.mark.parametrize("name", sorted(RETURN_NOTES))
def test_return_notes_describe_real_tools(name):
    assert hasattr(mcp_server, name)
