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
  speclock backup / restore FILE         # 完整备份 / 恢复数据库
  speclock export [--out DIR]            # 导出可读的 Markdown 快照（可进 git）
  speclock project list|create|rename    # 项目
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
    if not key and sys.stdin.isatty():
        import getpass

        key = getpass.getpass("请输入你的 admin / reviewer key（输入不显示）：").strip()
    if not key:
        sys.exit("缺少人类 key：设置 SPECLOCK_KEY、传 --key，或在终端里运行（会提示输入）")
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
        print("把下面这段合并进那个 Agent 所在目录的 .mcp.json（里面只有文件名，没有 key 本身）：")
        print(json.dumps(out["mcp_config"], ensure_ascii=False, indent=2))
        print(f"忘了 key 的内容可以用  speclock key show {out['id']}  查看。")
        return
    print(f"已创建 #{out['id']}（角色 {out['role']}）。密钥只显示这一次，请立即保存：")
    print(out["key"])


def _local_config():
    from speclock.home import NotInitialised, load_config

    try:
        return load_config()
    except NotInitialised as exc:
        sys.exit(str(exc))


def cmd_backup(args) -> None:
    from pathlib import Path

    from speclock import exporter

    cfg = _local_config()
    try:
        out = exporter.backup_db(cfg, Path(args.out) if args.out else None)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
    print(f"已备份到 {out}（{out.stat().st_size // 1024} KB）。含全部版本历史、审核单、执行记录和密钥哈希，请妥善保管。")
    print(f"恢复：停掉服务后运行  speclock restore {out}")


def cmd_restore(args) -> None:
    from pathlib import Path

    from speclock import exporter

    cfg = _local_config()
    try:
        kept = exporter.restore_db(cfg, Path(args.file))
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(str(exc))
    print(f"已用 {args.file} 恢复数据库。")
    if kept:
        print(f"原来的库改名保留在 {kept}，确认没问题后可以删掉。")


def cmd_export(args) -> None:
    from pathlib import Path

    from speclock import db as dbmod
    from speclock import exporter

    cfg = _local_config()
    dbmod.configure(cfg.db_url)
    out = Path(args.out) if args.out else cfg.home / "export"
    session = dbmod.SessionLocal()
    try:
        stats = exporter.export_spec(session, out)
    except OSError as exc:
        sys.exit(str(exc))
    finally:
        session.close()
    print(f"已导出到 {out}：{stats['projects']} 个项目、{stats['blocks']} 个模块、{stats['change_requests']} 张审核单。")
    if stats["archived_blocks"]:
        print(f"（{stats['archived_blocks']} 个已归档模块没有导出，它们在完整备份里。）")
    print("这是只读快照，可以提交进 git；要完整备份请用  speclock backup")


def cmd_project_list(args) -> None:
    c, _ = _client(args)
    for p in _request(c, "GET", "/api/v1/projects"):
        print(f"#{p['id']:<4} {p['name']}")


def cmd_project_create(args) -> None:
    c, _ = _client(args)
    out = _request(c, "POST", "/api/v1/projects", json={"name": args.name})
    print(f"已创建项目 #{out['id']}「{out['name']}」")


def cmd_project_rename(args) -> None:
    c, _ = _client(args)
    out = _request(c, "PUT", f"/api/v1/projects/{args.id}", json={"name": args.name})
    print(f"项目 #{out['id']} 已改名为「{out['name']}」")


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
    out = _request(c, "DELETE", f"/api/v1/keys/{args.id}", params={"via": "cli"})
    print(f"已删除 #{out['id']}")


def cmd_init(args) -> None:
    from pathlib import Path

    from speclock.home import NotInitialised, init_home

    if not args.glob:
        from speclock.home import locate_home

        existing, how = locate_home()
        if existing is not None and existing != Path.cwd() / ".speclock" and not (Path.cwd() / ".speclock").exists():
            print(f"提示：{how}已经有一份数据（{existing}）。这里会新建一个独立的 .speclock/，"
                  "之后在这个目录里运行的命令都会用新建的这一份。")
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
    if args.new_admin:
        revoked = 0
        if args.revoke_old:
            from speclock import db as dbmod
            from speclock.auth import hash_key
            from speclock.models import ApiKey

            session = dbmod.SessionLocal()
            try:
                for old in session.query(ApiKey).all():
                    if old.role is not None and old.role.name == "admin" and old.key != hash_key(key):
                        session.delete(old)
                        revoked += 1
                session.commit()
            finally:
                session.close()
        print()
        print(f"新的 admin key（只显示这一次，请自己保管）：{key}")
        if args.revoke_old:
            print(f"已吊销旧的 admin key：{revoked} 把。")
        else:
            print("旧的 admin key **仍然有效**。如果它是泄露了，请吊销：")
            print("  speclock init --new-admin --revoke-old        # 再发一把并吊销所有旧的 admin key")
            print("  或 speclock key list / speclock key delete <id>  # 只删指定的")
        return
    print()
    print(f"admin key（拥有全部权限，只显示这一次，请自己保管）：{key}")
    print()
    print("这把 key 是你自己的钥匙：**不要**写进项目里的 .mcp.json 或任何 Agent 读得到的文件，")
    print("否则同目录的 Agent 都有了管理员权限，可以自己批准自己的审核单。")
    print("  - 你自己的命令（speclock key create / cr approve …）会在终端里提示你输入它，不用存。")
    print("  - 要让 Claude 之类的客户端以管理员身份代你操作：配在**用户级**的 MCP 配置里，不要配在项目的 .mcp.json。")
    print()
    print("下一步：")
    print("  1. speclock serve                                  # 启动服务和网页")
    print("  2. speclock key create --role requirements-agent --label 需求")
    print("     为每个 Agent 创建它自己的 key，会打印可以直接贴进它的 .mcp.json 的配置。")


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
    ini.add_argument("--revoke-old", action="store_true", help="配合 --new-admin：同时吊销所有旧的 admin key（admin key 泄露时用）")
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

    bk = sub.add_parser("backup", help="完整备份数据库（含全部历史；灾难恢复用）")
    bk.add_argument("--out", help="备份文件路径（默认 .speclock/backups/speclock-时间.db）")
    bk.set_defaults(fn=cmd_backup)
    rs = sub.add_parser("restore", help="用备份文件恢复数据库（先停掉服务）")
    rs.add_argument("file")
    rs.set_defaults(fn=cmd_restore)
    ex = sub.add_parser("export", help="把当前规格和审核单导出成 Markdown + spec.json（可进 git，只读快照）")
    ex.add_argument("--out", help="导出目录（默认 .speclock/export）")
    ex.set_defaults(fn=cmd_export)
    pj = sub.add_parser("project", help="项目").add_subparsers(dest="cmd", required=True)
    pj.add_parser("list", help="列出项目").set_defaults(fn=cmd_project_list)
    pc = pj.add_parser("create", help="创建项目（需要 admin key）")
    pc.add_argument("name")
    pc.set_defaults(fn=cmd_project_create)
    pr = pj.add_parser("rename", help="项目改名（需要 admin key）")
    pr.add_argument("id", type=int)
    pr.add_argument("name")
    pr.set_defaults(fn=cmd_project_rename)
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
