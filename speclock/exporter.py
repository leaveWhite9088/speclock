"""导出与备份（本机操作，直接读 .speclock/ 里的数据库，不走 HTTP、不需要 key）。

两件不同的事：

- ``backup_db`` / ``restore_db``：**完整备份**。用 SQLite 的在线备份把整个库拷成一个文件，
  含全部版本历史、审核单、执行记录、密钥哈希；灾难恢复用。
- ``export_spec``：**可读的文本导出**。把当前已发布的规格和审核单写成 Markdown + 一份 spec.json，
  输出稳定（不含时间戳、按 id 排序），可以提交进 git，用来共享、对照历史、审阅。
  这是单向的快照，不能再导回库里（要还原请用 backup / restore）。
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from speclock.home import Config
from speclock.models import (
    Block,
    BlockVersion,
    Business,
    Capability,
    ChangeRequest,
    ExecutionRecord,
    Project,
)

MARKER = ".speclock-export"


# ---------- 完整备份 ----------


def backup_db(cfg: Config, out: Path | None = None) -> Path:
    """把数据库完整备份成一个文件（SQLite 在线备份，服务在跑也安全）。"""
    src = cfg.db_path
    if not src.is_file():
        raise FileNotFoundError(f"找不到数据库：{src}")
    if out is None:
        out = cfg.home / "backups" / f"speclock-{datetime.now():%Y%m%d-%H%M%S}.db"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"{out} 已经存在，换一个文件名")
    source = sqlite3.connect(str(src))
    dest = sqlite3.connect(str(out))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return out


def _service_running(cfg: Config) -> bool:
    try:
        with socket.create_connection((cfg.host, cfg.port), timeout=0.5):
            return True
    except OSError:
        return False


def restore_db(cfg: Config, src: Path) -> Path | None:
    """用备份文件替换当前数据库。原来的库先改名留着（返回它的路径）。服务在运行时拒绝。"""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"找不到备份文件：{src}")
    if _service_running(cfg):
        raise RuntimeError(f"服务还在运行（{cfg.url}），请先停掉 speclock serve 再恢复")
    check = sqlite3.connect(str(src))
    try:
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"projects", "api_keys", "blocks"} <= tables:
            raise ValueError(f"{src} 不是 SpecLock 的数据库备份")
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"{src} 已损坏（完整性检查没通过）")
    finally:
        check.close()
    kept = None
    if cfg.db_path.is_file():
        kept = cfg.db_path.with_name(f"{cfg.db_path.name}-before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        cfg.db_path.rename(kept)
    shutil.copyfile(src, cfg.db_path)
    return kept


# ---------- 文本导出 ----------


def _slug(text: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", text.strip()).strip("-.")
    return s[:40] or "未命名"


def _name(obj_id: int, title: str) -> str:
    return f"{obj_id}-{_slug(title)}"


def _jl(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _items_md(items: list[dict]) -> str:
    if not items:
        return "（无）\n"
    return "".join(f"- **{i.get('id', '')} {i.get('name', '')}**：{i.get('detail', '')}\n" for i in items)


def _current_version(db: Session, block: Block) -> BlockVersion | None:
    if not block.current_published_version:
        return None
    return (
        db.query(BlockVersion)
        .filter(BlockVersion.block_id == block.id, BlockVersion.version == block.current_published_version)
        .first()
    )


def _block_md(db: Session, block: Block, bv: BlockVersion) -> tuple[str, dict]:
    rules = _jl(bv.rules_json, [])
    acceptance = _jl(bv.acceptance_json, [])
    apis = _jl(bv.apis_json, [])
    rec = (
        db.query(ExecutionRecord)
        .filter(ExecutionRecord.block_id == block.id, ExecutionRecord.version == bv.version)
        .order_by(ExecutionRecord.id.desc())
        .first()
    )
    status = rec.status if rec else "—"
    md = (
        f"# {block.title}\n\n"
        f"- 模块 id：{block.id}　版本：**{bv.version}**（{bv.level or '—'}）　执行状态：{status}\n"
        f"- 最近一次变更：{bv.change_note or '—'}"
        + (f"（审核单 #{bv.cr_id}）" if bv.cr_id else "")
        + "\n\n"
    )
    if block.summary:
        md += f"> {block.summary}\n\n"
    md += f"## 业务背景\n\n{bv.content_md or '（无）'}\n\n"
    md += f"## 业务规则\n\n{_items_md(rules)}\n"
    md += f"## 验收条件\n\n{_items_md(acceptance)}\n"
    md += "## API\n\n"
    md += "".join(
        f"### {a.get('name', '')}　`{a.get('api', '')}`\n\n{a.get('desc', '')}\n\n"
        f"```json\n{json.dumps({k: a.get(k) for k in ('request', 'response')}, ensure_ascii=False, indent=2)}\n```\n\n"
        for a in apis
    ) or "（无）\n"
    data = {
        "id": block.id,
        "title": block.title,
        "summary": block.summary,
        "version": bv.version,
        "level": bv.level,
        "execution_status": status,
        "content_md": bv.content_md,
        "rules": rules,
        "acceptance": acceptance,
        "apis": apis,
    }
    return md, data


def _cr_md(cr: ChangeRequest) -> str:
    obsolete = _jl(cr.obsolete_json, [])
    md = (
        f"# 审核单 #{cr.id}：{cr.title}\n\n"
        f"- 状态：**{cr.status}**　类型：{'内部整理（Agent 自行判定）' if cr.kind == 'internal' else '业务变更'}\n"
    )
    if cr.kind == "internal":
        md += f"- 为什么不算业务变更：{cr.kind_reason}\n"
    if cr.decided_by:
        md += f"- 决定：{cr.decided_by}（{cr.decision_via}）{cr.decision_note}\n"
        if cr.decision_evidence:
            md += f"- 依据（原话）：{cr.decision_evidence}\n"
    md += f"\n## 为什么变\n\n{cr.intent or '（无）'}\n\n## 变成什么样\n\n{cr.expected_outcome or '（无）'}\n\n"
    md += "## 不再成立的旧认知\n\n" + ("".join(f"- {o}\n" for o in obsolete) or "（无）\n") + "\n"
    md += f"## 验收条件\n\n{_items_md(_jl(cr.acceptance_json, []))}\n"
    if cr.impact_note:
        md += f"## 影响说明\n\n{cr.impact_note}\n\n"
    md += "## Commit\n\n"
    md += "".join(
        f"- #{c.seq}：{c.change_note}（覆盖 {', '.join(_jl(c.covers_json, [])) or '无'}）\n" for c in cr.commits
    ) or "（无）\n"
    return md


def export_spec(db: Session, out: Path) -> dict:
    """把当前已发布的规格与全部审核单导出到 out。返回统计。输出不含时间戳，按 id 排序，git 里 diff 干净。"""
    out = Path(out)
    if out.exists() and any(out.iterdir()) and not (out / MARKER).exists():
        raise FileExistsError(f"{out} 不是空目录，也不是以前导出的目录，为免误删已拒绝；请换一个目录")
    if out.exists():
        for child in out.iterdir():  # 只清掉自己生成的内容（上面已确认是导出目录）
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("由 speclock export 生成，下次导出会整个重写，请不要手改。\n", encoding="utf-8")
    (out / "README.md").write_text(
        "# SpecLock 导出\n\n由 `speclock export` 生成的**只读快照**：当前已发布的规格与全部审核单。\n"
        "内容不含时间戳，可以提交进 git 对照历史。不能导回 SpecLock；要还原请用 `speclock restore`。\n\n"
        "- `index.md`：总目录\n- `<项目>/<大业务>/<小业务>/<模块>.md`：每个模块的当前版本\n"
        "- `change-requests/`：每张审核单\n- `spec.json`：同样的内容，机器可读\n",
        encoding="utf-8",
    )

    stats = {"projects": 0, "blocks": 0, "archived_blocks": 0, "change_requests": 0}
    tree: list[dict] = []
    index = "# 目录\n\n"
    for project in db.query(Project).order_by(Project.id):
        stats["projects"] += 1
        pdir = out / _name(project.id, project.name)
        ptree = {"id": project.id, "name": project.name, "businesses": []}
        index += f"## {project.name}\n\n"
        for biz in db.query(Business).filter(Business.project_id == project.id).order_by(Business.id):
            btree = {"id": biz.id, "name": biz.name, "capabilities": []}
            index += f"### {biz.name}\n\n"
            for cap in db.query(Capability).filter(Capability.business_id == biz.id).order_by(Capability.id):
                cdir = pdir / _name(biz.id, biz.name) / _name(cap.id, cap.title)
                cdir.mkdir(parents=True, exist_ok=True)
                ctree = {"id": cap.id, "title": cap.title, "summary": cap.summary,
                         "version": cap.current_version, "blocks": []}
                (cdir / "README.md").write_text(
                    f"# {cap.title}\n\n小业务 id：{cap.id}　当前版本：{cap.current_version or '—'}\n\n{cap.summary}\n",
                    encoding="utf-8",
                )
                index += f"- **{cap.title}**（{cap.current_version or '—'}）\n"
                for block in db.query(Block).filter(Block.capability_id == cap.id).order_by(Block.id):
                    if block.status == "archived":
                        stats["archived_blocks"] += 1
                        continue
                    bv = _current_version(db, block)
                    if bv is None:
                        continue
                    md, data = _block_md(db, block, bv)
                    (cdir / f"{_name(block.id, block.title)}.md").write_text(md, encoding="utf-8")
                    ctree["blocks"].append(data)
                    stats["blocks"] += 1
                    index += f"  - {block.title}　{bv.version}\n"
                btree["capabilities"].append(ctree)
            index += "\n"
            ptree["businesses"].append(btree)
        tree.append(ptree)
    if stats["archived_blocks"]:
        index += f"\n（已归档的 {stats['archived_blocks']} 个模块没有导出；它们在完整备份里。）\n"
    (out / "index.md").write_text(index, encoding="utf-8")

    crdir = out / "change-requests"
    crdir.mkdir(exist_ok=True)
    crs = []
    for cr in db.query(ChangeRequest).order_by(ChangeRequest.id):
        stats["change_requests"] += 1
        (crdir / f"{_name(cr.id, cr.title)}.md").write_text(_cr_md(cr), encoding="utf-8")
        crs.append({"id": cr.id, "project_id": cr.project_id, "title": cr.title, "status": cr.status,
                    "kind": cr.kind, "intent": cr.intent, "expected_outcome": cr.expected_outcome,
                    "acceptance": _jl(cr.acceptance_json, [])})
    (out / "spec.json").write_text(
        json.dumps({"projects": tree, "change_requests": crs}, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return stats
