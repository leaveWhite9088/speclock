"""端到端验收：用真实的 MCP（stdio 子进程 + 真实 HTTP）走一遍「语义复核」。

    python tools/e2e_review.py http://127.0.0.1:8031

前提：目标服务用「空库」（python -m speclock.seed --empty）启动，默认 admin key。
脚本里有三个会话，各用自己的 key 起一个 MCP server 进程：admin、需求 Agent、扫描 Agent，
所有操作都走 MCP 工具，不直接调 REST。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
ADMIN = os.environ.get("SPECLOCK_ADMIN_KEY", "human-dev-0000000000000000000000000001")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f"  —— {detail}" if detail and not ok else ""))


async def open_session(stack: AsyncExitStack, key: str) -> ClientSession:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "speclock.mcp_server"], cwd=ROOT,
        env={**os.environ, "SPECLOCK_URL": URL, "SPECLOCK_KEY": key},
    )
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def call(session: ClientSession, tool: str, **args):
    r = await session.call_tool(tool, args)
    text = "".join(c.text for c in r.content if getattr(c, "text", None))
    try:
        data = json.loads(text)
    except ValueError:
        return {"status": None, "body": text}
    return data


def body(r):
    return r["body"] if isinstance(r, dict) and "body" in r else r


async def main() -> None:
    async with AsyncExitStack() as stack:
        admin = await open_session(stack, ADMIN)
        me = body(await call(admin, "whoami"))
        assert me["role"] == "admin", me
        tools = [t.name for t in (await admin.list_tools()).tools]
        check("MCP 工具集包含复核工具", {"list_pending_reviews", "review_commit"} <= set(tools), str(tools))

        # ---------- 准备：两把 key（需求 Agent、扫描 Agent） ----------
        req_key = body(await call(admin, "create_api_key", role="requirements-agent", label="e2e 需求", evidence="e2e 脚本：创建", project_id=1))["key"]
        scan_key = body(await call(admin, "create_api_key", role="scanner-agent", label="e2e 扫描", evidence="e2e 脚本：创建", project_id=1))["key"]
        req = await open_session(stack, req_key)
        scan = await open_session(stack, scan_key)
        print("\n身份")
        scan_me = body(await call(scan, "whoami"))
        check("scanner-agent 有 cr.read 和 cr.review，没有 cr.write / commit.write",
              {"cr.read", "cr.review"} <= set(scan_me["permissions"])
              and not {"cr.write", "commit.write"} & set(scan_me["permissions"]), str(scan_me["permissions"]))

        # ---------- 建立初始规格（业务变更单，人批准） ----------
        cr = body(await call(req, "create_change_request", title="建立退款规格", intent="先把退款讲清楚",
                             expected_outcome="退款有明确的规则", project_id=1,
                             acceptance=[{"name": "规格成型", "detail": "退款规则与验收条件都已写入"}]))
        cr = body(await call(req, "submit_change_request", cr_id=cr["id"]))
        await call(admin, "approve_change_request", cr_id=cr["id"], content_hash=cr["content_hash"], evidence="同意（e2e）")
        block_ops = [
            {"op": "create_business", "name": "社区小店", "ref": "biz"},
            {"op": "create_capability", "business": "$biz", "title": "订单管理", "ref": "cap"},
            {"op": "create_block", "capability": "$cap", "title": "退款", "ref": "blk",
             "content_md": "# 退款\n\n顾客对已完成的订单申请退款的业务规则与验收口径。",
             "rules": [{"name": "退款期限", "detail": "顾客在订单完成后七日内可以申请退款，超过七日不再受理"},
                       {"name": "运费", "detail": "退款金额包含顾客已经支付的运费部分"}],
             "apis": [], "acceptance": [{"name": "超期不可退", "detail": "超过七日的退款申请被拒绝"}]},
        ]
        r = await call(req, "submit_commit", cr_id=cr["id"], ops=block_ops, covers=["AC-1"])
        block_id = body(r)["created"]["$blk"]["id"]
        cap_id = body(r)["created"]["$cap"]["id"]
        await call(req, "complete_change_request", cr_id=cr["id"])

        async def block():
            return body(await call(scan, "get_block", block_id=block_id))

        async def internal_cr(session, title, reason):
            c = body(await call(session, "create_change_request", title=title, intent="整理", expected_outcome="整理后业务含义不变",
                                project_id=1, kind="internal", kind_reason=reason,
                                acceptance=[{"name": "含义不变", "detail": "规则的意思没有变"}]))
            c = body(await call(session, "submit_change_request", cr_id=c["id"]))
            return c

        def typo_op(detail, rid="R-1", name="退款期限"):
            return [{"op": "update_block", "id": block_id,
                     "rule_ops": [{"op": "upsert", "id": rid, "entry": {"name": name, "detail": detail}}]}]

        base = await block()
        old_detail = base["rules"][0]["detail"]
        new_detail = "顾客在订单完成后7日内可以申请退款，超过7日不再受理"

        # ---------- 验收 1：改一个错别字 → 待复核，复核前规格没变，复核通过后才发布 ----------
        print("\n1. 错别字 → 待复核 → 复核通过")
        c1 = await internal_cr(req, "统一数字写法", "把汉字数字改成阿拉伯数字，意思没变")
        check("内部整理单提交即生效（agent_declared）", c1["status"] == "approved" and c1["decision_via"] == "agent_declared")
        r = await call(req, "submit_commit", cr_id=c1["id"], ops=typo_op(new_detail), covers=["AC-1"])
        check("提交后状态是 pending_review（HTTP 202）", r["status"] == 202 and body(r)["status"] == "pending_review", str(r)[:200])
        commit1 = body(r)["commit_id"]
        mid = await block()
        check("复核前规格没变、没有新版本", mid["rules"][0]["detail"] == old_detail and mid["version"] == base["version"])
        pend = body(await call(scan, "list_pending_reviews"))
        check("扫描 Agent 的待复核列表里有它，带新旧对比",
              len(pend) == 1 and pend[0]["review"]["changes"][0]["old"] == old_detail and pend[0]["review"]["changes"][0]["new"] == new_detail)
        ctx = body(await call(scan, "get_change_request", cr_id=c1["id"]))
        check("扫描 Agent 能读审核单（有 cr.read）", ctx["id"] == c1["id"] and ctx["commits"][0]["status"] == "pending_review")
        done = await call(req, "complete_change_request", cr_id=c1["id"])
        check("还有待复核的 Commit 时不能完成审核单", done["status"] == 409)
        ok = await call(scan, "review_commit", cr_id=c1["id"], commit_id=commit1, decision="approve", reason="只是汉字数字改阿拉伯数字，意思没变")
        check("扫描 Agent 复核通过 → 生效", ok["status"] == 200 and body(ok)["status"] == "applied", str(ok)[:200])
        after = await block()
        check("复核通过后才发布新版本，规则文字已更新", after["rules"][0]["detail"] == new_detail and after["version"] != base["version"])
        ctx = body(await call(scan, "get_change_request", cr_id=c1["id"]))
        rv = ctx["commits"][0]["review"]
        check("记录了复核人、理由、新旧对比",
              rv["decision"] == "approved" and rv["reviewed_by"] and rv["reviewed_by"] != ctx["commits"][0]["created_by"]
              and "意思没变" in rv["reason"] and rv["changes"][0]["old"] == old_detail)
        check("审核单可以完成", (await call(req, "complete_change_request", cr_id=c1["id"]))["status"] == 200)
        acts = body(await call(admin, "get_diff", block_id=block_id))
        check("版本对比里能看到这次改动", acts is not None)

        # ---------- 验收 2：提交者自己复核自己 → 403 ----------
        print("\n2. 自己复核自己")
        c2 = await internal_cr(admin, "admin 自己提交", "改一个标点")
        r = await call(admin, "submit_commit", cr_id=c2["id"], ops=typo_op(new_detail.replace("，", ",")), covers=["AC-1"])
        check("admin 提交的错别字 Commit 进入待复核", r["status"] == 202, str(r)[:160])
        own = await call(admin, "review_commit", cr_id=c2["id"], commit_id=body(r)["commit_id"], decision="approve", reason="自己通过自己")
        check("同一把 key 复核自己 → 403", own["status"] == 403 and "自己提交" in json.dumps(own, ensure_ascii=False), str(own)[:200])
        req_try = await call(req, "review_commit", cr_id=c2["id"], commit_id=body(r)["commit_id"], decision="approve", reason="x")
        check("需求 Agent 没有 cr.review → 403", req_try["status"] == 403)

        # ---------- 验收 3：复核不通过 → 不生效，原因可见 ----------
        print("\n3. 复核不通过")
        pending_id = body(r)["commit_id"]
        bad = await call(scan, "review_commit", cr_id=c2["id"], commit_id=pending_id, decision="reject",
                         reason="把全角逗号换成半角后断句不一致，需要业务确认")
        check("扫描 Agent 复核不通过", bad["status"] == 200 and body(bad)["status"] == "review_rejected")
        cur = await block()
        check("规格没有变化", cur["rules"][0]["detail"] == new_detail and cur["version"] == after["version"])
        ctx = body(await call(req, "get_change_request", cr_id=c2["id"]))
        c = ctx["commits"][0]
        check("原因对提交者可见", c["status"] == "review_rejected" and "断句不一致" in c["review"]["reason"], str(c["review"])[:200])

        # ---------- 验收 4：错别字 + 实质改动混在一批 → 整体拒绝并指出哪条 ----------
        print("\n4. 同一批里既有错别字又有实质改动")
        c4 = await internal_cr(req, "顺手整理", "改个标点，再顺手补一条规则")
        mixed = [{"op": "update_block", "id": block_id, "rule_ops": [
            {"op": "upsert", "id": "R-1", "entry": {"name": "退款期限", "detail": new_detail.replace("，", ",")}},
            {"op": "upsert", "entry": {"name": "手续费", "detail": "退款不收取任何手续费，由店铺承担"}},
        ]}]
        r = await call(req, "submit_commit", cr_id=c4["id"], ops=mixed, covers=["AC-1"])
        d = body(r)["detail"] if isinstance(body(r), dict) and "detail" in body(r) else {}
        sub = d.get("substantive", []) if isinstance(d, dict) else []
        check("整体按第 3 档拒绝（422）", r["status"] == 422, str(r)[:200])
        check("指出哪条是实质改动", any("手续费" in x["where"] and "新增" in x["why"] for x in sub), str(sub))
        check("没有残留的待复核 Commit", body(await call(scan, "list_pending_reviews")) == [])
        check("规格没有被改", (await block())["rules"][0]["detail"] == new_detail)

        # ---------- 验收 5：改名 / 搬动 / 合并 → 和以前完全一致 ----------
        print("\n5. 条目总和不变：改名 / 搬动 / 合并")
        c5 = await internal_cr(req, "改名并整理", "只改名字、搬动、合并，内容原样保留")
        r = await call(req, "submit_commit", cr_id=c5["id"],
                       ops=[{"op": "update_capability", "id": cap_id, "title": "订单中心"}], covers=["AC-1"])
        check("改名：直接生效（200，applied）", r["status"] == 200 and body(r)["status"] == "applied", str(r)[:160])
        # 搬动：先用业务变更单建第二个小业务
        cb = body(await call(req, "create_change_request", title="新建第二小业务", intent="分组", expected_outcome="多一个小业务", project_id=1,
                             acceptance=[{"name": "建好", "detail": "第二个小业务存在"}]))
        cb = body(await call(req, "submit_change_request", cr_id=cb["id"]))
        await call(admin, "approve_change_request", cr_id=cb["id"], content_hash=cb["content_hash"], evidence="同意（e2e）")
        rr = await call(req, "submit_commit", cr_id=cb["id"], covers=["AC-1"],
                        ops=[{"op": "create_capability", "business": 1, "title": "订单附加信息", "ref": "cap2"}])
        cap2 = body(rr)["created"]["$cap2"]["id"]
        await call(req, "complete_change_request", cr_id=cb["id"])
        r = await call(req, "submit_commit", cr_id=c5["id"], ops=[{"op": "move_block", "id": block_id, "capability": cap2}], covers=["AC-1"])
        check("搬动：直接生效", r["status"] == 200 and body(r)["status"] == "applied" and body(r)["moved_blocks"] == [block_id], str(r)[:160])
        cur = await block()
        merged = [{"op": "create_block", "capability": cap2, "title": "退款（合并后）",
                   "content_md": "# 退款\n\n合并后的退款模块，规则与验收条件原样保留。",
                   "rules": [{"name": e["name"], "detail": e["detail"]} for e in cur["rules"]],
                   "apis": [], "acceptance": [{"name": e["name"], "detail": e["detail"]} for e in cur["acceptance"]]},
                  {"op": "archive_block", "id": block_id}]
        r = await call(req, "submit_commit", cr_id=c5["id"], ops=merged, covers=["AC-1"])
        check("合并（新建相同内容 + 归档旧的）：直接生效", r["status"] == 200 and body(r)["status"] == "applied", str(r)[:200])

        # ---------- 验收 6：scanner 的边界 ----------
        print("\n6. scanner-agent 的边界")
        no1 = await call(scan, "create_change_request", title="x", intent="x", expected_outcome="x", project_id=1,
                         acceptance=[{"name": "a", "detail": "b"}])
        no2 = await call(scan, "submit_commit", cr_id=c5["id"], ops=[{"op": "archive_block", "id": 1}])
        check("不能开审核单（403）", no1["status"] == 403)
        check("不能提交 Commit（403）", no2["status"] == 403)

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    for name, _ok, detail in failed:
        print("  失败：", name, detail)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
