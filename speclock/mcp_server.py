"""SpecLock MCP server (stdio).

Exactly 6 tools — the full agent surface. Every tool is a thin HTTP client
of the SpecLock read-only REST API; there is intentionally no write tool
(proposals are the only mutation, and they land in the review queue, never
in the published store).

Configure with:
  SPECLOCK_BASE_URL   default http://127.0.0.1:8000
  SPECLOCK_AGENT_KEY  an agent-* key printed by `python -m speclock.seed`

Run:  python -m speclock.mcp_server
"""

from __future__ import annotations

import json
import os

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("SPECLOCK_BASE_URL", "http://127.0.0.1:8000")
AGENT_KEY = os.environ.get("SPECLOCK_AGENT_KEY", "")

mcp = MCPServer("speclock")


def _call(method: str, path: str, **kwargs) -> str:
    if not AGENT_KEY:
        return json.dumps({"error": "SPECLOCK_AGENT_KEY is not set"}, ensure_ascii=False)
    try:
        r = httpx.request(
            method,
            f"{BASE_URL}{path}",
            headers={"X-API-Key": AGENT_KEY},
            timeout=30,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"cannot reach SpecLock at {BASE_URL}: {exc}"},
                          ensure_ascii=False)
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return json.dumps({"status": r.status_code, "body": body}, ensure_ascii=False)


@mcp.tool(description=(
    "List one-line summaries of all published blocks. Call this FIRST to "
    "decide which blocks are relevant, then fetch only those with get_block."
))
def get_index() -> str:
    return _call("GET", "/api/v1/index")


@mcp.tool(description=(
    "Fetch one published block. Pin a version (e.g. '1.2.0') to guarantee a "
    "stable snapshot for the whole task; omit it for the latest published."
))
def get_block(block_id: int, version: str = "") -> str:
    ref = f"{block_id}@{version}" if version else str(block_id)
    return _call("GET", f"/api/v1/blocks/{ref}")


@mcp.tool(description="Structured + text diff between two published versions of a block.")
def get_diff(block_id: int, from_version: str, to_version: str) -> str:
    return _call("GET", f"/api/v1/blocks/{block_id}/diff",
                 params={"from": from_version, "to": to_version})


@mcp.tool(description="Receipt: declare 'I implemented against block {id} @ {version}'.")
def ack_block(block_id: int, version: str, task_desc: str = "") -> str:
    return _call("POST", f"/api/v1/blocks/{block_id}/ack",
                 json={"version": version, "task_desc": task_desc})


@mcp.tool(description=(
    "Submit a change proposal — the ONLY way an agent can influence the "
    "document store. A human must approve and publish it before it takes "
    "effect; poll with get_proposal."
))
def submit_proposal(
    block_id: int,
    description: str,
    suggestion: str,
    scenario: str = "",
    proposed_content_md: str = "",
    proposed_openapi_yaml: str = "",
) -> str:
    body: dict = {
        "block_id": block_id,
        "description": description,
        "suggestion": suggestion,
        "scenario": scenario,
    }
    if proposed_content_md:
        body["proposed_content_md"] = proposed_content_md
    if proposed_openapi_yaml:
        body["proposed_openapi_yaml"] = proposed_openapi_yaml
    return _call("POST", "/api/v1/proposals", json=body)


@mcp.tool(description="Poll the status of a proposal (submitted / published / rejected).")
def get_proposal(proposal_id: int) -> str:
    return _call("GET", f"/api/v1/proposals/{proposal_id}")


def main() -> None:
    mcp.run()  # stdio transport (default)


if __name__ == "__main__":
    main()
