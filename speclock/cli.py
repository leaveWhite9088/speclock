"""SpecLock 命令行：人用人类 key 查看并批准 / 驳回审核单（Change Request）。

批准是人的授权动作，只能用 ``cr.approve`` 权限的人类 key 完成；agent 类 key 一律 403。
这是审核页按钮之外的另一个渠道，两者在 Core 看来等价（Core 只认"出示了人类 key"），
批准记录里会留下渠道（via=cli）。

环境变量：
  SPECLOCK_URL   默认 http://127.0.0.1:8000
  SPECLOCK_KEY   人类 key（也可用 --key）

用法：
  speclock-cli cr list [--status pending_review]
  speclock-cli cr show 12
  speclock-cli cr approve 12                 # 先打印内容，确认后批准
  speclock-cli cr approve 12 --hash 3fa9c2…  # 凭你看过的内容哈希（前缀即可）批准，不再交互
  speclock-cli cr approve 12 --via natural_language --evidence "同意，按这个来"
  speclock-cli cr reject 12 --reason "验收条件没写清楚"
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def _client(args) -> tuple[httpx.Client, str]:
    key = args.key or os.environ.get("SPECLOCK_KEY", "")
    if not key:
        sys.exit("缺少人类 key：设置 SPECLOCK_KEY 或传 --key")
    base = (args.url or os.environ.get("SPECLOCK_URL") or "http://127.0.0.1:8000").rstrip("/")
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
    print(f"审核单 #{cr['id']}  [{cr['status']}]  {cr['title']}")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="speclock-cli", description=__doc__.split("\n\n")[0])
    p.add_argument("--url", help="SpecLock 地址（默认取 SPECLOCK_URL）")
    p.add_argument("--key", help="人类 key（默认取 SPECLOCK_KEY）")
    sub = p.add_subparsers(dest="group", required=True)
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
    ap.add_argument("--via", default="cli", choices=["cli", "natural_language", "button", "api"])
    ap.add_argument("--evidence", help="via=natural_language 时必填：人的原话")
    ap.add_argument("--note", help="批准备注")
    ap.set_defaults(fn=cmd_approve)

    rj = cr.add_parser("reject", help="驳回（必须写理由）")
    rj.add_argument("id", type=int)
    rj.add_argument("--reason", required=True)
    rj.add_argument("--via", default="cli", choices=["cli", "natural_language", "button", "api"])
    rj.add_argument("--evidence")
    rj.set_defaults(fn=cmd_reject)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
