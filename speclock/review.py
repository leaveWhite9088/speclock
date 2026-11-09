"""内部整理的三档判定（确定性，不含 LLM）。

内部整理单（kind=internal）由需求 Agent 声明「不改变业务内容」。Commit 落地前，Core 比较
整理前后项目里「在线」模块的规则 / 验收条件 / API，分三档：

1. **条目总和完全不变**（改名、搬动、拆分、合并）：机械通过，直接生效。
2. **条目的字变了，但还是同一条、改动很小**（错别字、标点、个别措辞）：不直接拒绝，也不直接
   生效。把新旧文字逐条记下来，Commit 进入「待复核」，规格暂时不变；由**另一个角色**复核通过
   后才应用（复核者不能是提交者，按 key 判定）。语义对不对由复核者判断，Core 只做机械的事。
3. **有实质增、删、改**（新建 / 归档 / 恢复模块、增删条目、改 API、整条重写、改动超过阈值、
   涉及条目太多）：拒绝，要求改开业务变更单让人批准。

「同一条」靠稳定 id（R-n / AC-n）判断，不靠名称；第 2 档的阈值在 ``speclock.toml`` 的
``[review]`` 节里配置（见 ``settings.ReviewSettings``）。第 1 档和第 3 档不依赖任何人的判断。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from speclock import diffing
from speclock.models import Block, Business, Capability
from speclock.settings import ReviewSettings, load_settings

KIND_LABEL = {"rule": "规则", "ac": "验收条件", "api": "API"}


def get_review_settings() -> ReviewSettings:
    return load_settings().review


# ---------- 快照与条目总和 ----------


def entry_key(kind: str, entry: dict) -> tuple:
    """条目的规范形式（忽略编号，只看内容），用来比较「条目总和」是否不变。"""
    clean = {k: v for k, v in entry.items() if k != "id"}
    return (kind, json.dumps(clean, ensure_ascii=False, sort_keys=True))


def snapshot(db: Session, project_id: int, extra_block_ids=()) -> dict[int, dict]:
    """项目里「在线」模块（已发布且未归档，或 extra_block_ids 里本 Commit 刚新建、尚未发布的）
    的规则 / 验收条件 / API，按模块 id 索引。"""
    snap: dict[int, dict] = {}
    blocks = (
        db.query(Block)
        .join(Capability, Capability.id == Block.capability_id)
        .join(Business, Business.id == Capability.business_id)
        .filter(Business.project_id == project_id)
        .all()
    )
    for b in blocks:
        if b.status != "published" and b.id not in extra_block_ids:
            continue
        apis = json.loads(b.draft_apis_json or "[]")
        try:  # 先规范化，避免默认值 / 字段顺序造成假差异
            apis = diffing.validate_apis(apis, require_desc=False)
        except diffing.ApisValidationError:
            pass
        snap[b.id] = {
            "title": b.title,
            "rules": json.loads(b.draft_rules_json or "[]"),
            "acceptance": json.loads(b.draft_acceptance_json or "[]"),
            "apis": apis,
        }
    return snap


def signature(snap: dict[int, dict]) -> Counter:
    """所有在线模块的条目总和（多重集合，忽略编号和所在模块）。"""
    sig: Counter = Counter()
    for block in snap.values():
        for kind, key in (("rule", "rules"), ("ac", "acceptance"), ("api", "apis")):
            for entry in block[key]:
                sig[entry_key(kind, entry)] += 1
    return sig


def describe(key: tuple) -> str:
    kind, blob = key
    entry = json.loads(blob)
    return f"{KIND_LABEL[kind]}「{entry.get('name') or entry.get('api') or ''}」"


# ---------- 编辑距离 ----------


def edit_distance(a: str, b: str, limit: int | None = None) -> int:
    """Levenshtein 距离；给了 limit，超过它就提前返回 limit + 1（够判定阈值了，也避免长文本慢）。"""
    if a == b:
        return 0
    if limit is not None and abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if limit is not None and min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _small_edit(old: str, new: str, cfg: ReviewSettings) -> tuple[bool, int, float, str]:
    """返回 (是否算小改动, 编辑距离, 改动比例, 不算的原因)。"""
    if len(old) > cfg.max_text_len or len(new) > cfg.max_text_len:
        return False, -1, 1.0, f"文字超过 {cfg.max_text_len} 个字，不做逐字对比"
    if not old.strip() or not new.strip():
        return False, -1, 1.0, "整段新增或清空"
    dist = edit_distance(old, new, cfg.max_edit_chars)
    ratio = round(dist / max(len(old), len(new)), 3)
    if dist > cfg.max_edit_chars:
        return False, dist, ratio, f"改动超过 {cfg.max_edit_chars} 个字"
    if ratio > cfg.max_edit_ratio:
        return False, dist, ratio, f"改动占原文 {ratio:.0%}，超过上限 {cfg.max_edit_ratio:.0%}"
    return True, dist, ratio, ""


# ---------- 判定 ----------


@dataclass
class Verdict:
    tier: int  # 1 机械通过 / 2 待复核 / 3 实质改动
    changes: list[dict] = field(default_factory=list)  # 第 2 档：逐条新旧对比
    substantive: list[dict] = field(default_factory=list)  # 第 3 档：实质改动及原因
    thresholds: dict = field(default_factory=dict)

    def record(self) -> dict:
        """存进 Commit.review_json 的内容。"""
        return {"tier": self.tier, "changes": self.changes, "thresholds": self.thresholds}

    def fingerprint(self) -> list[tuple]:
        """复核通过、重新应用时用来确认「规格没有在提交之后又变过」。"""
        return sorted(
            (c["block_id"], c["kind"], c["item_id"], c["field"], c["old"], c["new"]) for c in self.changes
        )


def _api_map(block: dict) -> dict[str, dict]:
    return {a.get("api", ""): a for a in block["apis"]}


def classify(before: dict[int, dict], after: dict[int, dict], cfg: ReviewSettings) -> Verdict:
    sig_before, sig_after = signature(before), signature(after)
    thresholds = {
        "max_entries": cfg.max_entries,
        "max_edit_chars": cfg.max_edit_chars,
        "max_edit_ratio": cfg.max_edit_ratio,
    }
    if sig_before == sig_after:
        return Verdict(tier=1, thresholds=thresholds)

    substantive: list[dict] = []
    changes: list[dict] = []

    def reject(where: str, why: str) -> None:
        substantive.append({"where": where, "why": why})

    appeared = sorted(set(after) - set(before))
    gone = sorted(set(before) - set(after))
    if appeared:
        names = "、".join(f"#{i}「{after[i]['title']}」" for i in appeared)
        reject(f"模块 {names}", "新建或恢复了模块，条目总和因此增加")
    if gone:
        names = "、".join(f"#{i}「{before[i]['title']}」" for i in gone)
        reject(f"模块 {names}", "归档了模块，条目总和因此减少")

    for bid in sorted(set(before) & set(after)):
        b, a = before[bid], after[bid]
        where = f"模块 #{bid}「{a['title']}」"
        # API：任何差异都是实质改动
        bm, am = _api_map(b), _api_map(a)
        for name in sorted(set(am) - set(bm)):
            reject(f"{where} API {name}", "新增了 API")
        for name in sorted(set(bm) - set(am)):
            reject(f"{where} API {name}", "删除了 API（或改了它的方法 / 路径）")
        for name in sorted(set(bm) & set(am)):
            if entry_key("api", bm[name]) != entry_key("api", am[name]):
                reject(f"{where} API {name}", "改了 API 的字段或说明")
        # 规则 / 验收条件：按稳定 id 对应同一条
        for kind, key in (("rule", "rules"), ("ac", "acceptance")):
            label = KIND_LABEL[kind]
            old_by_id = {e["id"]: e for e in b[key] if e.get("id")}
            new_ids = {e["id"] for e in a[key] if e.get("id")}
            for e in a[key]:
                eid = e.get("id")
                if not eid or eid not in old_by_id:
                    reject(f"{where} {label}「{e.get('name', '')}」", f"新增了{label}")
                    continue
                old = old_by_id[eid]
                for fld, fld_label in (("name", "名称"), ("detail", "详述")):
                    o, n = old.get(fld, ""), e.get(fld, "")
                    if o == n:
                        continue
                    ok, dist, ratio, why = _small_edit(o, n, cfg)
                    if ok:
                        changes.append({
                            "block_id": bid, "block_title": a["title"], "kind": kind, "item_id": eid,
                            "field": fld, "old": o, "new": n, "distance": dist, "ratio": ratio,
                        })
                    else:
                        reject(f"{where} {label} {eid} 的{fld_label}", why)
            for eid in sorted(set(old_by_id) - new_ids):
                reject(f"{where} {label} {eid}「{old_by_id[eid].get('name', '')}」", f"删除了{label}")

    touched = {(c["block_id"], c["kind"], c["item_id"]) for c in changes}
    if not cfg.enabled and changes:
        reject("全部改动", "语义复核没有启用（speclock.toml 的 [review] enabled = false）")
    elif len(touched) > cfg.max_entries:
        reject("全部改动", f"涉及 {len(touched)} 条条目，超过上限 {cfg.max_entries}")

    # 对账：把小改动套用到「整理前」的条目总和上，必须正好等于「整理后」，否则说明有改动没被解释清楚
    if not substantive:
        adjusted = Counter(sig_before)
        for bid, block in before.items():
            for kind, key in (("rule", "rules"), ("ac", "acceptance")):
                for e in block[key]:
                    mine = [c for c in changes if (c["block_id"], c["kind"], c["item_id"]) == (bid, kind, e.get("id"))]
                    if not mine:
                        continue
                    new_e = dict(e)
                    for c in mine:
                        new_e[c["field"]] = c["new"]
                    adjusted[entry_key(kind, e)] -= 1
                    adjusted[entry_key(kind, new_e)] += 1
        if any(v < 0 for v in adjusted.values()) or +adjusted != sig_after:
            reject("全部改动", "有改动无法逐条对应到某一条规则 / 验收条件的文字修改")

    if substantive:
        return Verdict(tier=3, changes=changes, substantive=substantive, thresholds=thresholds)
    changes.sort(key=lambda c: (c["block_id"], c["kind"], c["item_id"], c["field"]))
    return Verdict(tier=2, changes=changes, thresholds=thresholds)


def reject_detail(verdict: Verdict, before: dict[int, dict], after: dict[int, dict]) -> dict:
    """第 3 档拒绝时的 422 说明：哪条是实质改动、为什么；保留旧字段 added_or_changed / removed_or_changed。"""
    sig_before, sig_after = signature(before), signature(after)
    sample = lambda c: [describe(k) for k in list(c)[:3]]  # noqa: E731
    return {
        "error": "这个审核单声明是「内部整理」，但这批改动改变了业务内容"
        "（规则 / 验收条件 / API 有实质增、删、改）。请改开「业务变更」审核单让人批准",
        "substantive": verdict.substantive,
        "minor_edits": [
            {k: c[k] for k in ("block_id", "item_id", "field", "old", "new")} for c in verdict.changes
        ],
        "added_or_changed": sample(sig_after - sig_before),
        "removed_or_changed": sample(sig_before - sig_after),
        "hint": "只有单条规则 / 验收条件里的小幅文字改动（错别字、标点、个别措辞）才会进入待复核；"
        "与实质改动混在同一批时，整批按业务变更处理",
    }
