"""SpecLock 命令行：初始化、启动服务，以及人用人类 key 查看并批准 / 驳回审核单（Change Request）、管理密钥。

批准是人的授权动作，只能用 ``cr.approve`` 权限的人类 key 完成；agent 类 key 一律 403。
这是对话（自然语言）批准之外的另一个渠道，两者在 Core 看来等价（Core 只认"出示了人类 key"），
批准记录里会留下渠道（via=cli）。

环境变量：
  SPECLOCK_URL   默认取 .speclock/config.toml 里的地址
  SPECLOCK_KEY   人类 key（也可用 --key）

用法：
  speclock init [--global]               # 创建 .speclock/，打印 admin key 和 .mcp.json 片段
  speclock serve                         # 启动服务和网页
  speclock mcp                           # 启动 MCP（给 Agent 用）
  speclock cr list [--status pending_review]
  speclock cr show 12
  speclock cr approve 12                 # 先打印内容，确认后批准
  speclock cr approve 12 --hash 3fa9c2…  # 凭你看过的内容哈希（前缀即可）批准，不再交互
  speclock cr approve 12 --via natural_language --evidence "同意，按这个来"
  speclock cr reject 12 --reason "验收条件没写清楚"
  speclock key list
  speclock key create --role executor-agent --label "后端执行 Agent" [--project 1]
  speclock key show 3                    # 查看一把已保存的 Agent key
  speclock key delete 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from speclock.home import default_url


def _client(args) -> tuple[httpx.Client, str]:
    key = args.key or os.environ.get("SPECLOCK_KEY", "")
    if not key:
        sys.exit("缺少人类 key：设置 SPECLOCK_KEY 或传 --key")
    base = (args.url or default_url()).rstrip("/")
    return httpx.Client(base_url=base, headers={"X-API-Key": key}, timeout=30), base


def _request(c: httpx.Client, method: str, path: str, **kw):
    try:
        r = c.request(method, path, **kw)
    except httpx.HTTPError as exc:
        sys.exit(f"连不上 SpecLock：{exc}")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        sys.exit(f"失败（HTTP {r.status_code}）：{detail}")
    return r.json()


def _print_cr(cr: dict) -> None:
    kind = "  【内部整理：Agent 自行判定，未经人批准】" if cr.get("kind") == "internal" else ""
    print(f"审核单 #{cr['id']}  [{cr['status']}]  {cr['title']}{kind}")
    if cr.get("kind_reason"):
        print(f"  不算业务变更的理由：{cr['kind_reason']}")
    print(f"  为什么变：{cr['intent']}")
    print(f"  变成什么样：{cr['expected_outcome']}")
    if cr["obsolete"]:
        print("  不再成立的旧认知：")
        for s in cr["obsolete"]:
            print(f"    - {s}")
    print("  验收条件：")
    for a in cr["acceptance"]:
        print(f"    {a['id']} {a['name']}：{a['detail']}")
    if cr["impact_note"]:
        print(f"  影响说明：{cr['impact_note']}")
    if cr["supersedes_id"]:
        print(f"  取代审核单：#{cr['supersedes_id']}")
    if cr["content_hash"]:
        print(f"  内容哈希：{cr['content_hash']}")
    if cr["decision_note"]:
        print(f"  决定备注：{cr['decision_note']}")


def cmd_list(args) -> None:
    c, _ = _client(args)
    params = {"status": args.status} if args.status else {}
    for cr in _request(c, "GET", "/api/v1/change-requests", params=params):
        print(f"#{cr['id']:<4} {cr['status']:<15} {cr['title']}")


def cmd_show(args) -> None:
    c, _ = _client(args)
    cr = _request(c, "GET", f"/api/v1/change-requests/{args.id}")
    _print_cr(cr)
    for commit in cr.get("commits", []):
        print(f"  Commit #{commit['seq']}：{commit['change_note']}（覆盖 {', '.join(commit['covers']) or '无'}）")


def cmd_approve(args) -> None:
    c, _ = _client(args)
    cr = _request(c, "GET", f"/api/v1/change-requests/{args.id}")
    if cr["status"] != "pending_review":
        sys.exit(f"审核单 #{cr['id']} 当前是 {cr['status']}，不在待审核状态")
    if args.hash:
        if not cr["content_hash"].startswith(args.hash):
            sys.exit("内容哈希对不上：审核单内容已变化，请重新查看后再批准")
    else:
        _print_cr(cr)
        if input("\n确认批准这个审核单？输入 yes 继续：").strip().lower() != "yes":
            sys.exit("已取消")
    body = {"content_hash": cr["content_hash"], "via": args.via,
            "evidence": args.evidence or "", "note": args.note or ""}
    out = _request(c, "POST", f"/api/v1/change-requests/{args.id}/approve", json=body)
    print(f"已批准 #{out['id']}（渠道 {out['decision_via']}）")


def cmd_reject(args) -> None:
    c, _ = _client(args)
    body = {"reason": args.reason, "via": args.via, "evidence": args.evidence or ""}
    out = _request(c, "POST", f"/api/v1/change-requests/{args.id}/reject", json=body)
    print(f"已驳回 #{out['id']}")


def cmd_key_list(args) -> None:
    c, _ = _client(args)
    for k in _request(c, "GET", "/api/v1/keys"):
        scope = f"项目 {k['project_id']}" if k["project_id"] else "全局"
        print(f"#{k['id']:<4} {k['hint']:<22} {k['role'] or '-':<20} {scope:<8} {k['label']}")


def cmd_key_create(args) -> None:
    c, _ = _client(args)
    body = {"role": args.role, "label": args.label or "", "via": "cli"}
    if args.project:
        body["project_id"] = args.project
    out = _request(c, "POST", "/api/v1/keys", json=body)
    if out.get("key_file"):
        print(f"已创建 #{out['id']}（角色 {out['role']}），key 已保存到 .speclock/keys/{out['key_file']}")
        print("把这个文件名交给要用它的 Agent（它自己去读，不要把内容贴进对话）；你可以用下面的命令查看：")
        print(f"  speclock key show {out['id']}")
        return
    print(f"已创建 #{out['id']}（角色 {out['role']}）。密钥只显示这一次，请立即保存：")
    print(out["key"])


def cmd_key_show(args) -> None:
    from speclock import keyfiles
    from speclock.home import find_home

    c, _ = _client(args)
    rows = [k for k in _request(c, "GET", "/api/v1/keys") if k["id"] == args.id]
    if not rows:
        sys.exit(f"没有 #{args.id} 这把 key")
    if not rows[0].get("key_file"):
        sys.exit("这把 key 没有存成文件（人类 key 只在创建时显示一次，请自己保管）")
    try:
        print(keyfiles.read_key(rows[0]["key_file"], find_home()))
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))


def cmd_key_delete(args) -> None:
    c, _ = _client(args)
    out = _request(c, "DELETE", f"/api/v1/keys/{args.id}")
    print(f"已删除 #{out['id']}")


def cmd_init(args) -> None:
    from pathlib import Path

    from speclock.home import NotInitialised, init_home

    try:
        cfg, key = init_home(Path.cwd(), glob=args.glob, project_name=args.project, port=args.port,
                              new_admin=args.new_admin)
    except NotInitialised as exc:
        sys.exit(str(exc))
    print(f"SpecLock 数据目录：{cfg.home}")
    print(f"服务地址：{cfg.url}（speclock serve 启动；网页同一个地址）")
    if key is None:
        print("这里已经初始化过，库里已有密钥（明文无法找回；admin key 丢了就运行 speclock init --new-admin 再发一把）。")
        return
    print()
    print(f"admin key（拥有全部权限，只显示这一次，请自己保管）：{key}")
    print()
    print("把下面这段合并进你项目的 .mcp.json，就能让 Agent 接入：")
    print(json.dumps({"mcpServers": {"speclock": {
        "command": "speclock", "args": ["mcp"],
        "env": {"SPECLOCK_URL": cfg.url, "SPECLOCK_KEY": key}}}}, indent=2))


def cmd_serve(args) -> None:
    from speclock.home import NotInitialised
    from speclock.main import run

    try:
        run()
    except NotInitialised as exc:
        sys.exit(str(exc))


def cmd_mcp(args) -> None:
    if args.key_file:
        os.environ["SPECLOCK_KEY_FILE"] = args.key_file
    from speclock.mcp_server import main as mcp_main

    mcp_main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="speclock", description=__doc__.split("\n\n")[0])
    p.add_argument("--url", help="SpecLock 地址（默认取 SPECLOCK_URL）")
    p.add_argument("--key", help="人类 key（默认取 SPECLOCK_KEY）")
    sub = p.add_subparsers(dest="group", required=True)
    ini = sub.add_parser("init", help="在当前目录创建 .speclock/（--global 则建在用户主目录）")
    ini.add_argument("--global", dest="glob", action="store_true", help="电脑级：~/.speclock，多个项目共用一个服务")
    ini.add_argument("--project", help="项目名（默认取当前目录名）")
    ini.add_argument("--port", type=int, help="端口（默认：项目级随机空闲端口，电脑级 47821）")
    ini.add_argument("--new-admin", action="store_true", help="admin key 丢了：再发一把新的（旧的不受影响，可用 key delete 吊销）")
    ini.set_defaults(fn=cmd_init)
    sub.add_parser("serve", help="启动服务和网页").set_defaults(fn=cmd_serve)
    mc = sub.add_parser("mcp", help="启动 MCP 服务（给 Agent 用，stdio）")
    mc.add_argument("--key-file", help="这个 Agent 的 key 文件（.speclock/keys/ 里的文件名，或路径）；不用把 key 写进配置")
    mc.set_defaults(fn=cmd_mcp)
    cr = sub.add_parser("cr", help="审核单").add_subparsers(dest="cmd", required=True)

    ls = cr.add_parser("list", help="列出审核单")
    ls.add_argument("--status")
    ls.set_defaults(fn=cmd_list)

    sh = cr.add_parser("show", help="查看一个审核单")
    sh.add_argument("id", type=int)
    sh.set_defaults(fn=cmd_show)

    ap = cr.add_parser("approve", help="批准")
    ap.add_argument("id", type=int)
    ap.add_argument("--hash", help="你看过的内容哈希（前缀即可）；给了就不再交互确认")
    ap.add_argument("--via", default="cli", choices=["cli", "natural_language", "api"])
    ap.add_argument("--evidence", help="via=natural_language 时必填：人的原话")
    ap.add_argument("--note", help="批准备注")
    ap.set_defaults(fn=cmd_approve)

    rj = cr.add_parser("reject", help="驳回（必须写理由）")
    rj.add_argument("id", type=int)
    rj.add_argument("--reason", required=True)
    rj.add_argument("--via", default="cli", choices=["cli", "natural_language", "api"])
    rj.add_argument("--evidence")
    rj.set_defaults(fn=cmd_reject)

    key = sub.add_parser("key", help="密钥").add_subparsers(dest="cmd", required=True)
    key.add_parser("list", help="列出密钥").set_defaults(fn=cmd_key_list)
    kc = key.add_parser("create", help="创建密钥（Agent 类 key 存成文件；人类 key 明文只显示一次）")
    kc.add_argument("--role", required=True, help="角色名，如 executor-agent / tester-agent")
    kc.add_argument("--label", help="备注，如这把 key 给谁用")
    kc.add_argument("--project", type=int, help="绑定到某个项目（不填 = 全局）")
    kc.set_defaults(fn=cmd_key_create)
    ks = key.add_parser("show", help="查看一把已保存的 Agent key（读 .speclock/keys/ 里的文件）")
    ks.add_argument("id", type=int)
    ks.set_defaults(fn=cmd_key_show)
    kd = key.add_parser("delete", help="删除密钥（对应的 key 文件一并删除）")
    kd.add_argument("id", type=int)
    kd.set_defaults(fn=cmd_key_delete)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
