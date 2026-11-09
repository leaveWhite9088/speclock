"""SpecLock MCP server (stdio).

A thin HTTP client of the SpecLock REST API. SpecLock itself is NOT an agent: it is a
service that external agents plug into through this server. What a key may do is decided
by its ROLE on the server (``whoami`` shows it); a tool the role lacks permission for
simply returns 403.

Tools:
- read the spec (``spec.read``): get_index, get_block, get_diff, get_capability,
  get_block_history, get_capability_history
- execution (``exec.read`` / ``exec.write`` / ``exec.verify``): list_work, get_work,
  claim_work, release_work, report_blocked, report_failed, submit_implementation (executor),
  verify_work (tester — must be a different key from the implementer)
- requirements agent (``cr.write`` / ``commit.write``): create / update / submit /
  withdraw a Change Request, submit a Commit under an APPROVED one, complete it.
- approve / reject a Change Request (``cr.approve``). In the current coding phase one
  admin key serves both the human and the agent, so the agent calls these on the human's
  behalf: it MUST pass the human's own words as ``evidence`` (and the content hash of the
  version the human saw), which the server records in the audit trail. Never approve
  without an explicit instruction from the human in the conversation.
- keys: create_api_key (``key.manage``, admin only) is a DANGEROUS operation — only after the
  human explicitly agreed in the conversation. use_api_key switches the key this session
  uses (no client restart needed), e.g. to a key you just created.

Configure with:
  SPECLOCK_URL        default http://127.0.0.1:8000 (legacy name SPECLOCK_BASE_URL also accepted)
  SPECLOCK_KEY        the agent's API key (legacy name SPECLOCK_AGENT_KEY also accepted)

Run:  python -m speclock.mcp_server
"""

from __future__ import annotations

import json
import os

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("SPECLOCK_URL") or os.environ.get(
    "SPECLOCK_BASE_URL", "http://127.0.0.1:8000"
)
CONFIGURED_KEY = os.environ.get("SPECLOCK_KEY") or os.environ.get("SPECLOCK_AGENT_KEY", "")
AGENT_KEY = CONFIGURED_KEY  # use_api_key 可在本进程内切换

mcp = MCPServer("speclock")


def _call(method: str, path: str, **kwargs) -> str:
    if not AGENT_KEY:
        return json.dumps({"error": "SPECLOCK_KEY is not set"}, ensure_ascii=False)
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


# ---------- who am I ----------


@mcp.tool(description=(
    "Who am I: this key's role, kind, project binding and the permissions the role grants. "
    "Call it first to know which of the other tools you may use."
))
def whoami() -> str:
    return _call("GET", "/api/v1/me")


# ---------- read the spec (spec.read) ----------


@mcp.tool(description=(
    "Navigation tree of all published modules: 大业务 → 小业务→ 模块, "
    "each module with a one-line summary and the execution status of its current "
    "version (work_id / execution_status). Call this FIRST to pick relevant modules "
    "from the tree, then fetch only those with get_block. To find things to do, use "
    "list_work instead. Optionally filter by business (exact 大业务 name). "
    "Requires spec.read."
))
def get_index(business: str = "") -> str:
    params: dict = {}
    if business:
        params["business"] = business
    return _call("GET", "/api/v1/index", params=params)


@mcp.tool(description=(
    "Fetch one published block: background (content_md), business rules, "
    "acceptance criteria and APIs. Rules and acceptance criteria are lists of "
    "{id, name, detail} whose ids (R-1 / AC-1) are stable — cite them by id. "
    "Pin a version (e.g. '1.2.0') to guarantee a stable snapshot for the whole "
    "task; omit it for the latest published. The response also carries "
    "'level' (a mechanically computed label for how this version differs from "
    "the previous one: major / minor / patch / initial — a hint only, it does "
    "not tell you what to do), 'status' ('current', or 'deprecated' with "
    "'superseded_by' when a newer version exists) and 'cr_id' / 'commit_id' "
    "(the Change Request and Commit that produced this version — read it with "
    "get_change_request to learn WHY it changed). Requires spec.read."
))
def get_block(block_id: int, version: str = "") -> str:
    ref = f"{block_id}@{version}" if version else str(block_id)
    return _call("GET", f"/api/v1/blocks/{ref}")


@mcp.tool(description=(
    "Structured + text diff between two published versions of a module "
    "(APIs, rules and acceptance criteria; entries are matched by stable id). "
    "from_version/to_version are optional: defaults to the two most recent "
    "published versions. Includes the mechanically computed 'level' label. "
    "Requires spec.read."
))
def get_diff(block_id: int, from_version: str = "", to_version: str = "") -> str:
    params: dict = {}
    if from_version:
        params["from"] = from_version
    if to_version:
        params["to"] = to_version
    return _call("GET", f"/api/v1/blocks/{block_id}/diff", params=params)


@mcp.tool(description=(
    "Fetch a capability manifest: which published version of each module the "
    "capability currently points at. Pin a capability version (e.g. '1.2.0') to "
    "replay a historical manifest. Requires spec.read."
))
def get_capability(capability_id: int, version: str = "") -> str:
    ref = f"{capability_id}@{version}" if version else str(capability_id)
    return _call("GET", f"/api/v1/capabilities/{ref}")


@mcp.tool(description=(
    "Version history of one module, oldest first: for every version its mechanical "
    "'level' label, change_note, delta (what was added / removed / modified, by stable "
    "id), the Change Request and Commit that produced it (cr_id / commit_id — read the "
    "request with get_change_request to learn WHY), and status ('current' or "
    "'deprecated' with 'superseded_by'). Use it to see how a module evolved; read a "
    "version's content with get_block (pin the version) and the difference between two "
    "versions with get_diff. Requires spec.read."
))
def get_block_history(block_id: int) -> str:
    return _call("GET", f"/api/v1/blocks/{block_id}/history")


@mcp.tool(description=(
    "Version history of one capability (小业务), oldest first: each version's manifest "
    "(module → version), which module triggered it, change_note, cr_id / commit_id and "
    "status. Replay one historical manifest with get_capability (pin the version). "
    "Requires spec.read."
))
def get_capability_history(capability_id: int) -> str:
    return _call("GET", f"/api/v1/capabilities/{capability_id}/history")


# ---------- execution (exec.read / exec.write / exec.verify) ----------


@mcp.tool(description=(
    "List execution records (the to-do queue). Every published module version gets one "
    "automatically. Filter by status: pending (waiting to be claimed), in_progress, "
    "blocked (stuck on a business question — the requirements agent should answer it "
    "through a Change Request), failed, implemented (waiting for independent "
    "verification), verified; optionally block_id / capability_id, or mine=true for the "
    "ones you claimed. Default: everything except superseded. Requires exec.read."
))
def list_work(
    status: str = "", block_id: int | None = None,
    capability_id: int | None = None, mine: bool = False,
) -> str:
    params: dict = {}
    if status:
        params["status"] = status
    if block_id is not None:
        params["block_id"] = block_id
    if capability_id is not None:
        params["capability_id"] = capability_id
    if mine:
        params["mine"] = "true"
    return _call("GET", "/api/v1/work", params=params)


@mcp.tool(description=(
    "One execution record with its event history, the results submitted so far and the "
    "FULL spec of exactly the version it targets (background, rules, acceptance "
    "criteria, APIs). Testers read this to see what the executor claims. "
    "Requires exec.read."
))
def get_work(work_id: int) -> str:
    return _call("GET", f"/api/v1/work/{work_id}")


@mcp.tool(description=(
    "Claim a task: pending / failed / blocked → in_progress. The response carries the "
    "full spec pinned to the version being claimed — work from THAT snapshot. If a newer "
    "version is published meanwhile, your later reports get 409 and you must claim the "
    "new record. Requires exec.write."
))
def claim_work(work_id: int) -> str:
    return _call("POST", f"/api/v1/work/{work_id}/claim")


@mcp.tool(description=(
    "Give up a task you claimed: in_progress → pending, so someone else can take it. "
    "Requires exec.write."
))
def release_work(work_id: int) -> str:
    return _call("POST", f"/api/v1/work/{work_id}/release")


@mcp.tool(description=(
    "Report you are blocked by a BUSINESS question (the spec is missing information or "
    "contradicts itself): in_progress → blocked, with the question as 'reason'. Do not "
    "guess the answer. The requirements agent resolves it by publishing a new version "
    "through a Change Request. Requires exec.write."
))
def report_blocked(work_id: int, reason: str) -> str:
    return _call("POST", f"/api/v1/work/{work_id}/blocked", json={"reason": reason})


@mcp.tool(description=(
    "Report that you could not finish the task: in_progress → failed, with the reason. "
    "A failed task can be claimed again (by you or anyone). Requires exec.write."
))
def report_failed(work_id: int, reason: str) -> str:
    return _call("POST", f"/api/v1/work/{work_id}/failed", json={"reason": reason})


@mcp.tool(description=(
    "Submit your implementation: in_progress → implemented. 'results' must contain ONE "
    "entry per acceptance criterion of the claimed version: {ac_id: 'AC-1', result: "
    "'pass', evidence: '<test output / response / what you observed>'}. Evidence is "
    "required. Every criterion must pass — if you cannot make one pass, use "
    "report_failed or report_blocked instead of submitting. 'evidence' here is PROOF of "
    "your test result (output, response, what you observed). A DIFFERENT key (the "
    "tester) then verifies it. Requires exec.write."
))
def submit_implementation(work_id: int, results: list[dict], note: str = "") -> str:
    return _call("POST", f"/api/v1/work/{work_id}/implementation",
                 json={"results": results, "note": note})


@mcp.tool(description=(
    "Independently verify an implemented task (tester only). Test it yourself against "
    "the pinned spec, then give ONE result per acceptance criterion: {ac_id, result: "
    "'pass' | 'fail', evidence}. All pass → verified; any fail → the task goes back to "
    "failed with your evidence as the reason. 'evidence' is proof of what YOU observed "
    "when testing. You cannot verify what you implemented (same key → 403). "
    "Requires exec.verify."
))
def verify_work(work_id: int, results: list[dict], note: str = "") -> str:
    return _call("POST", f"/api/v1/work/{work_id}/verification",
                 json={"results": results, "note": note})


# ---------- keys (key.manage) ----------


@mcp.tool(description=(
    "DANGEROUS — creates an API key (admin only; roles are granted permissions, so a new "
    "key is new power). Presets: requirements-agent, executor-agent, tester-agent, "
    "scanner-agent. NEVER do this on your own initiative: tell the human which role and "
    "why, wait for their explicit yes in this conversation, and pass THEIR words (the "
    "approval of creating this key, not test evidence) as 'evidence'. First check whether "
    "your own AGENTS.md or .mcp.json already holds a key for the role — never create a "
    "duplicate. The plaintext key is returned ONCE and works immediately: call "
    "use_api_key to act with it now, and record it in the AGENTS.md / MCP config of the "
    "agent that will use it long-term. Do not repeat the key in chat. project_id binds "
    "the key to one project. Requires key.manage."
))
def create_api_key(role: str, label: str, evidence: str, project_id: int | None = None) -> str:
    body: dict = {"role": role, "label": label, "via": "natural_language", "evidence": evidence}
    if project_id is not None:
        body["project_id"] = project_id
    return _call("POST", "/api/v1/keys", json=body)


@mcp.tool(description=(
    "Switch which API key this MCP session uses from now on — no client restart needed. "
    "Typical use: after create_api_key, use the new key right away (e.g. act as the "
    "tester). The key is checked with /me first; if it is not valid nothing changes. "
    "Pass an empty key to go back to the key this server was configured with. Returns "
    "the new identity (role and permissions). Only switch to a key you were given or "
    "created with the human's approval; remember that the verifier of a task must not "
    "be the key that implemented it."
))
def use_api_key(key: str = "") -> str:
    global AGENT_KEY
    candidate = key.strip() or CONFIGURED_KEY
    if not candidate:
        return json.dumps({"error": "SPECLOCK_KEY is not set and no key was given"},
                          ensure_ascii=False)
    previous, AGENT_KEY = AGENT_KEY, candidate
    result = json.loads(_call("GET", "/api/v1/me"))
    if result.get("status") != 200:
        AGENT_KEY = previous
        return json.dumps({"error": "该密钥无效，已保持原来的身份不变", "detail": result},
                          ensure_ascii=False)
    return json.dumps({"switched": True, "identity": result["body"]}, ensure_ascii=False)


# ---------- Change Requests (cr.read / cr.write / commit.write) ----------


@mcp.tool(description=(
    "List Change Requests (审核单) you can see, newest first. Optional status filter: "
    "draft / pending_review / approved / applied / rejected / superseded. Requires cr.read."
))
def list_change_requests(status: str = "") -> str:
    return _call("GET", "/api/v1/change-requests", params={"status": status} if status else {})


@mcp.tool(description=(
    "Fetch one Change Request with its status, acceptance coverage (which AC-n are "
    "covered by commits, which are missing), the human's decision (including the "
    "rejection reason when rejected) and its commits. Poll this to learn whether the "
    "human has approved. Requires cr.read."
))
def get_change_request(cr_id: int) -> str:
    return _call("GET", f"/api/v1/change-requests/{cr_id}")


@mcp.tool(description=(
    "Create a Change Request (审核单) as a DRAFT — the object through which a human "
    "authorizes a business change. It carries business intent ONLY, never which block to "
    "edit or any technology. Fields: title; intent (why the business changes); "
    "expected_outcome (what the business looks like afterwards); obsolete (list of old "
    "beliefs that no longer hold); acceptance (list of {name, detail}; the server assigns "
    "ids AC-1, AC-2 ... — at least one is required to submit); impact_note (a note for the "
    "human about what this affects). WRITING STYLE: the human reads all of these — write "
    "natural, fluent Chinese like explaining to a colleague, no spec-speak. project_id is "
    "optional when your key is bound to a project. supersedes_id replaces an earlier "
    "APPROVED-but-unfinished request when this one is approved. kind: 'business' "
    "(default — a human must approve it) or 'internal' (a pure reorganisation that does "
    "NOT change business content: rename, move a module to another capability, split or "
    "merge modules while every rule / acceptance item / API entry stays word for word). "
    "YOU judge which one it is; for 'internal' kind_reason must say why it is not a "
    "business change, and it needs the cr.internal permission. An internal request takes "
    "effect the moment you submit it (no human approval, but it is audited and shown to "
    "the human as 'decided by the agent'), and the server rejects its Commit if the "
    "total set of rules / acceptance items / APIs changed in any way — then open a "
    "business request instead. When in doubt choose 'business'. Requires cr.write."
))
def create_change_request(
    title: str,
    intent: str = "",
    expected_outcome: str = "",
    acceptance: list[dict] | None = None,
    obsolete: list[str] | None = None,
    impact_note: str = "",
    project_id: int | None = None,
    supersedes_id: int | None = None,
    kind: str = "business",
    kind_reason: str = "",
) -> str:
    body: dict = {
        "kind": kind,
        "kind_reason": kind_reason,
        "title": title,
        "intent": intent,
        "expected_outcome": expected_outcome,
        "acceptance": acceptance or [],
        "obsolete": obsolete or [],
        "impact_note": impact_note,
    }
    if project_id is not None:
        body["project_id"] = project_id
    if supersedes_id is not None:
        body["supersedes_id"] = supersedes_id
    return _call("POST", "/api/v1/change-requests", json=body)


@mcp.tool(description=(
    "Edit a DRAFT Change Request — only the fields you pass change. 'acceptance' replaces "
    "the whole list (keep an item's id to keep it the same item). A request that was "
    "submitted is frozen: withdraw_change_request first if you need to edit it. "
    "Requires cr.write."
))
def update_change_request(
    cr_id: int,
    title: str | None = None,
    intent: str | None = None,
    expected_outcome: str | None = None,
    acceptance: list[dict] | None = None,
    obsolete: list[str] | None = None,
    impact_note: str | None = None,
    supersedes_id: int | None = None,
    kind: str | None = None,
    kind_reason: str | None = None,
) -> str:
    body = {k: v for k, v in {
        "kind": kind, "kind_reason": kind_reason,
        "title": title, "intent": intent, "expected_outcome": expected_outcome,
        "acceptance": acceptance, "obsolete": obsolete, "impact_note": impact_note,
        "supersedes_id": supersedes_id,
    }.items() if v is not None}
    return _call("PUT", f"/api/v1/change-requests/{cr_id}", json=body)


@mcp.tool(description=(
    "Submit a draft Change Request (draft → pending_review; only the key that created it, "
    "or an admin, may edit / submit / withdraw a draft). An 'internal' request skips the "
    "human and becomes approved immediately (see create_change_request). Its content "
    "is frozen and hashed; the human then approves or rejects it themselves — you cannot "
    "approve it on your own: show the human the content, wait for their explicit decision, "
    "then use approve_change_request / reject_change_request with their words. "
    "Intent, expected_outcome and at least one acceptance item are required. "
    "Requires cr.write."
))
def submit_change_request(cr_id: int) -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/submit")


@mcp.tool(description=(
    "Withdraw a pending_review Change Request back to draft so it can be edited again "
    "(the earlier content hash becomes void). Requires cr.write."
))
def withdraw_change_request(cr_id: int) -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/withdraw")


@mcp.tool(description=(
    "Approve a pending_review Change Request ON BEHALF OF THE HUMAN. Only call this after "
    "the human has explicitly told you, in this conversation, to approve THIS request — "
    "after you showed them its content. 'content_hash' is the hash from get_change_request "
    "of the version the human saw (409 if the request has changed since); 'evidence' is the "
    "human's own words approving it, quoted verbatim (required, recorded in the audit "
    "trail). Never approve a request you wrote just because it seems fine. "
    "Requires cr.approve."
))
def approve_change_request(cr_id: int, content_hash: str, evidence: str, note: str = "") -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/approve",
                 json={"content_hash": content_hash, "via": "natural_language",
                       "evidence": evidence, "note": note})


@mcp.tool(description=(
    "Reject a pending_review Change Request ON BEHALF OF THE HUMAN, with their reason "
    "(required; the requirements agent reads it and opens a new request instead of editing "
    "this one — rejected is final). 'evidence' is the human's own words, quoted verbatim. "
    "Requires cr.approve."
))
def reject_change_request(cr_id: int, reason: str, evidence: str = "") -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/reject",
                 json={"reason": reason, "via": "natural_language",
                       "evidence": evidence or reason})


@mcp.tool(description=(
    "Write to the spec database: submit an atomic Commit under an APPROVED Change Request. "
    "All ops succeed and are published together, or none is applied. 'ops' is an ordered "
    "list; each has an 'op' field: create_business {name, ref?}; update_business {id, "
    "name}; create_capability {business, title, summary?, ref?}; update_capability {id, "
    "title?, summary?}; create_block {capability, title, summary?, content_md, rules, apis, "
    "acceptance, ref?} (must be complete: background >= 20 chars, >= 1 rule, >= 1 "
    "acceptance item, every API with desc); update_block {id, title?, summary?, "
    "content_md?, and per list EITHER a full replacement (rules / apis / acceptance) OR "
    "incremental ops (rule_ops / api_ops / acceptance_ops)}; archive_block {id}; "
    "restore_block {id}; move_block {id, capability} moves a published module under "
    "another capability of the same project, keeping its identity, history and work "
    "records. Objects created earlier in the same commit can be referenced "
    "wherever an id is expected: give the creating op a 'ref' name, then write that "
    "name WITH a '$' prefix as a plain string, e.g. create_business {name:'运营', "
    "ref:'biz'} then create_capability {business:'$biz', title:'日报', ref:'cap'} then "
    "create_block {capability:'$cap', ...} — not {'$ref': 'biz'}. Incremental ops "
    "locate items by STABLE id (R-n / AC-n from get_block): {op:'upsert', id, entry:"
    "{name, detail}} modifies, upsert without id adds, {op:'delete', id} removes; api_ops "
    "locate by 'api' ('GET /path'). In a full replacement only items that carry their id "
    "count as the same item. Unknown ids → 409. 'covers' lists which of the request's "
    "acceptance ids (AC-n) this commit satisfies (may be empty, e.g. for an "
    "archive-only commit); complete_change_request requires "
    "every AC to be covered by some commit. Each touched block gets a new version whose "
    "'level' label is computed mechanically; each touched capability gets exactly one "
    "new version. Use dry_run=true to preview versions/levels/deltas without writing. "
    "Requires commit.write."
))
def submit_commit(
    cr_id: int,
    ops: list[dict],
    covers: list[str] | None = None,
    change_note: str = "",
    dry_run: bool = False,
) -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/commits",
                 json={"ops": ops, "covers": covers or [], "change_note": change_note,
                       "dryRun": dry_run})


@mcp.tool(description=(
    "Report that every change the approved Change Request asked for has been written "
    "(approved → applied). The server checks mechanically that every acceptance item is "
    "covered by at least one commit and returns 409 listing the missing ones otherwise. "
    "This says the SPEC is written — not that any code is implemented or verified. "
    "Requires commit.write."
))
def complete_change_request(cr_id: int) -> str:
    return _call("POST", f"/api/v1/change-requests/{cr_id}/complete")


def main() -> None:
    mcp.run()  # stdio transport (default)


if __name__ == "__main__":
    main()
