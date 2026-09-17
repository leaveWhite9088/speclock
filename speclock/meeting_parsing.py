"""会议记录源文件解析：精准需求 / 业务事实两类切块文件的伪 YAML parser。

源格式是 minutes2reqs 产物——固定 2 空格缩进的伪 YAML 列表项，逐行扫描
实现，不引第三方 YAML 库。解析失败抛 MeetingParseError（含行号 / 期望
格式 / 实际内容），由 API 层格式化成可直接贴给 agent 修源文件的中文报错。

切块即真相源：块编辑后经 render_file 渲染回完整文件。prose 块（标题行、
会议概括、覆盖校验等散文节）原样保存 raw 文本，与条目块按 seq 拼接，
保证导出 = 完整文件。
"""

from __future__ import annotations

import re

# 切块文件类型：只有这两类会被 parse 成 chunks
CHUNKED_KINDS = {"requirements", "facts"}

ALL_KINDS = ["requirements", "facts", "confirm", "transcript", "questions", "glossary", "other"]

_KIND_SUFFIXES = [
    ("_精准需求.md", "requirements"),
    ("_业务事实.md", "facts"),
    ("_需求确认单.md", "confirm"),
    ("_内部问题清单.md", "questions"),
    ("_修正词表.md", "glossary"),
    ("_转写.md", "transcript"),  # 必须在带后缀的更长形式之后匹配
]

# 派生物后缀：一律归为 other（整篇存储，不切块），最先判断
_DERIVED_SUFFIX = "_精简.md"

# 精准需求文件的条目分节 → chunk_type / ref_id 前缀
_REQ_ITEM_SECTIONS = {
    "需求清单": ("req", "REQ"),
    "约束清单": ("con", "CON"),
    "行动项清单": ("act", "ACT"),
    "待澄清Q": ("q", "Q"),
}

CHUNK_TYPE_PREFIX = {"req": "REQ", "fact": "FACT", "con": "CON", "act": "ACT", "q": "Q"}
_PREFIX_CHUNK_TYPE = {v: k for k, v in CHUNK_TYPE_PREFIX.items()}

# 条目级标量字段（source 单独处理，其余 key 一律报错）
# meeting/constraint/deadline 是真实文件里出现过的合法变体字段
_SCALAR_KEYS = {"statement", "status", "confirm", "based_on", "owner", "question", "suggest",
                "category", "meeting", "constraint", "deadline", "备注"}

# 渲染时的字段顺序（严格对齐 minutes2reqs 源格式）
_FIELD_ORDER = ["statement", "question", "constraint", "category", "owner", "deadline", "status",
                "confirm", "based_on", "suggest", "meeting", "备注"]


class MeetingParseError(Exception):
    """源文件格式错误：line 为 1 起始行号，expected/actual 供 API 层拼中文报错。"""

    def __init__(self, line: int, expected: str, actual: str):
        self.line = line
        self.expected = expected
        self.actual = actual
        super().__init__(f"第 {line} 行：期望 {expected}；实际内容：{actual!r}")


def detect_kind(filename: str) -> str:
    """按文件名后缀识别类型。两种命名都兼容：`xx_转写_精准需求.md` 与
    `xx_精准需求.md`（无 _转写 中缀）——两者都以 _精准需求.md 结尾。"""
    if filename.endswith(_DERIVED_SUFFIX):
        return "other"
    for suffix, kind in _KIND_SUFFIXES:
        if filename.endswith(suffix):
            return kind
    return "other"


def parse_meeting_date(dir_name: str) -> str | None:
    """从目录名 YYMMDD- 前缀解析会议日期（→ "20YY-MM-DD"），不合法返回 None。"""
    m = re.match(r"^(\d{2})(\d{2})(\d{2})-", dir_name or "")
    if not m:
        return None
    yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    return f"20{yy:02d}-{mm:02d}-{dd:02d}"


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return v


def _parse_quotes(lines: list[str], i: int) -> tuple[list[dict], int]:
    """解析 source: 下的 quote 列表（4 空格 '- quote:' + 6 空格 at/speaker）。"""
    quotes: list[dict] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            break
        if not line.startswith("    - quote:"):
            break
        q = {"quote": _strip_quotes(line[len("    - quote:"):])}
        i += 1
        for key in ("at", "speaker"):
            prefix = f"      {key}:"
            if i >= len(lines) or not lines[i].startswith(prefix):
                actual = lines[i] if i < len(lines) else "<文件结束>"
                raise MeetingParseError(i + 1, f'{prefix} ...（quote 的 {key} 字段，6 空格缩进）', actual)
            q[key] = _strip_quotes(lines[i][len(prefix):])
            i += 1
        quotes.append(q)
    if not quotes:
        actual = lines[i] if i < len(lines) else "<文件结束>"
        raise MeetingParseError(i + 1, '    - quote: "..."（source: 下至少一条引用，4 空格缩进）', actual)
    return quotes, i


def _parse_item(lines: list[str], i: int, expected_prefix: str | None) -> tuple[dict, int]:
    """解析一个条目块（lines[i] 为 '- id: XXX'），返回 (fields, next_i)。

    fields 含全部标量字段 + quotes 列表；id 在 fields["id"] 里。
    expected_prefix 为 None 时接受任意已知前缀（REQ/CON/ACT/Q/FACT），
    条目类型由 id 自身前缀决定（真实文件中存在 CON 条目放在 REQ 分节、
    条目无分节直接跟在标题后等变体）。
    """
    first = lines[i]
    m = re.match(r"^- id:\s*(\S+)\s*$", first)
    if not m:
        raise MeetingParseError(i + 1, "- id: XXX-xx（条目起始行）", first)
    ref_id = m.group(1)
    pm = re.match(r"^([A-Za-z]+)-\d+$", ref_id)
    if not pm or pm.group(1) not in _PREFIX_CHUNK_TYPE:
        raise MeetingParseError(
            i + 1, f"id 形如 {'/'.join(_PREFIX_CHUNK_TYPE)}-数字", first
        )
    if expected_prefix and pm.group(1) != expected_prefix:
        raise MeetingParseError(
            i + 1, f"id 形如 {expected_prefix}-数字（当前分节的条目前缀）", first
        )
    prefix = pm.group(1)
    fields: dict = {"id": ref_id}
    i += 1
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            break
        if not line.startswith("  "):
            break  # 条目结束，交还外层扫描
        body = line[2:]
        if line.startswith("   "):
            # 缩进错误的字段行（真实文件存在 6 空格 备注:）：能识别为合法字段则宽容接受
            m2 = re.match(r"^([^\s:]+):\s*(.*)$", line.strip())
            if m2 and m2.group(1) in _SCALAR_KEYS and m2.group(1) not in fields:
                fields[m2.group(1)] = _strip_quotes(m2.group(2))
                i += 1
                continue
            raise MeetingParseError(i + 1, "2 空格缩进的字段行（key: value）", line)
        if body == "source:":
            quotes, i = _parse_quotes(lines, i + 1)
            fields["quotes"] = quotes
            continue
        m = re.match(r"^([^\s:]+):\s*(.*)$", body)
        if not m:
            raise MeetingParseError(i + 1, "key: value 字段行（2 空格缩进）", line)
        key = m.group(1)
        if key not in _SCALAR_KEYS:
            raise MeetingParseError(
                i + 1,
                f"字段名为 {'/'.join(sorted(_SCALAR_KEYS))} 之一，或 source:",
                line,
            )
        if key in fields:
            raise MeetingParseError(i + 1, f"字段 {key} 在条目内只出现一次", line)
        fields[key] = _strip_quotes(m.group(2))
        i += 1
    # Q 条目真实变体：有的文件用 statement 而不是 question 承载问题
    required_ok = (
        (fields.get("question") or fields.get("statement"))
        if prefix == "Q"
        else fields.get("statement")
    )
    if not required_ok:
        required = "question 或 statement" if prefix == "Q" else "statement"
        if i < len(lines) and lines[i].strip():
            raise MeetingParseError(
                i + 1, f"2 空格缩进的 {required}: 字段行（属于条目 {ref_id}）", lines[i]
            )
        raise MeetingParseError(i, f"条目 {ref_id} 含 {required}: 字段", "<条目提前结束>")
    return fields, i


def _item_chunk(fields: dict, chunk_type: str, section: str) -> dict:
    ref_id = fields["id"]
    rest = {k: v for k, v in fields.items() if k != "id"}
    return {
        "chunk_type": chunk_type,
        "section": section,
        "ref_id": ref_id,
        "fields": rest,
        "text_md": render_item(ref_id, rest),
    }


def _prose_chunk(raw: str, section: str) -> dict:
    return {
        "chunk_type": "prose",
        "section": section,
        "ref_id": None,
        "fields": {"raw": raw},
        "text_md": raw,
    }


def parse_items(text: str, kind: str) -> list[dict]:
    """把切块文件全文解析成按序 chunk 列表（不含 seq，由调用方编号）。

    失败抛 MeetingParseError。kind 必须是 requirements / facts。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # 源文件可能是 CRLF
    if kind == "requirements":
        return _parse_requirements(text)
    if kind == "facts":
        return _parse_facts(text)
    raise ValueError(f"kind {kind!r} 不是切块文件类型")


def _parse_intro_prose(lines: list[str], i: int, chunks: list[dict]) -> int:
    """标题行之后、首个 ## 分节之前允许有引言散文（真实文件存在这种变体），
    收为一个 prose 块；返回推进后的行下标。"""
    n = len(lines)
    intro: list[str] = []
    while i < n and not lines[i].startswith(("## ", "### ", "- id:")):
        intro.append(lines[i])
        i += 1
    while intro and not intro[-1].strip():
        intro.pop()
    if any(l.strip() for l in intro):
        chunks.append(_prose_chunk("\n".join(intro), ""))
    return i


def _parse_facts(text: str) -> list[dict]:
    lines = text.split("\n")
    n = len(lines)
    chunks: list[dict] = []
    i = 0
    while i < n and not lines[i].strip():
        i += 1
    if i >= n or not lines[i].startswith("# "):
        actual = lines[i] if i < n else "<空文件>"
        raise MeetingParseError(i + 1, "# 标题（文件第一行）", actual)
    chunks.append(_prose_chunk(lines[i], ""))
    i += 1
    i = _parse_intro_prose(lines, i, chunks)
    section = ""
    seen_fact = False
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            if not section:
                raise MeetingParseError(i + 1, "## <分类> 分节标题（标题非空）", line)
            chunks.append(_prose_chunk(line, section))
            i += 1
            continue
        if line.startswith("- id:"):
            fields, i = _parse_item(lines, i, "FACT")
            if section:
                fields.setdefault("category", section)
                item_section_name = section
            else:
                # 无 ## 分节的变体：条目自带 category 字段，用它作为归属分节
                item_section_name = fields.get("category") or "未分类"
            chunks.append(_item_chunk(fields, "fact", item_section_name))
            seen_fact = True
            continue
        # 散文段落（如 ## 会议概括 的正文）：收为 prose 块
        body = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].startswith(("#", "- id:")):
            body.append(lines[i])
            i += 1
        chunks.append(_prose_chunk("\n".join(body), section))
    if not seen_fact:
        raise MeetingParseError(n, "至少一条 - id: FACT-xx 条目", "<未找到任何条目>")
    return chunks


def _parse_requirements(text: str) -> list[dict]:
    lines = text.split("\n")
    n = len(lines)
    chunks: list[dict] = []
    i = 0
    while i < n and not lines[i].strip():
        i += 1
    if i >= n or not lines[i].startswith("# "):
        actual = lines[i] if i < n else "<空文件>"
        raise MeetingParseError(i + 1, "# 标题（文件第一行）", actual)
    chunks.append(_prose_chunk(lines[i], ""))
    i += 1
    i = _parse_intro_prose(lines, i, chunks)
    section = ""
    item_section: tuple[str, str] | None = None  # 当前条目分节 (chunk_type, 前缀)
    seen_item = False
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("### "):
            if item_section is None:
                raise MeetingParseError(i + 1, "### 分组标题只允许出现在条目分节内", line)
            section = line[4:].strip()
            chunks.append(_prose_chunk(line, section))
            i += 1
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            if title in _REQ_ITEM_SECTIONS:
                item_section = _REQ_ITEM_SECTIONS[title]
                section = title
                chunks.append(_prose_chunk(line, section))
                i += 1
            else:
                # 散文节（会议概括 / 覆盖校验等）：标题 + 正文整体存为一个 prose 块
                item_section = None
                section = title
                body = [line]
                i += 1
                while i < n:
                    nxt = lines[i]
                    if nxt.startswith("#") or nxt.startswith("- id:"):
                        break
                    body.append(nxt)
                    i += 1
                while len(body) > 1 and not body[-1].strip():
                    body.pop()
                chunks.append(_prose_chunk("\n".join(body), section))
            continue
        if line.startswith("- id:"):
            fields, i = _parse_item(lines, i, None)  # 条目类型由 id 自身前缀决定
            chunk_type = _PREFIX_CHUNK_TYPE[fields["id"].split("-")[0]]
            chunks.append(_item_chunk(fields, chunk_type, section))
            seen_item = True
            continue
        # 分节内/分节间的说明性散文（如 约束清单 下"（本场无约束）"备注段）：收为 prose 块
        body = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].startswith(("#", "- id:")):
            body.append(lines[i])
            i += 1
        chunks.append(_prose_chunk("\n".join(body), section))
    if not seen_item:
        raise MeetingParseError(n, "至少一条 REQ/CON/ACT/Q 条目", "<未找到任何条目>")
    return chunks


def render_item(ref_id: str, fields: dict) -> str:
    """把条目块渲染回伪 YAML 列表项（字段顺序对齐源格式）。"""
    out = [f"- id: {ref_id}"]
    emitted: set[str] = set()
    for key in _FIELD_ORDER:
        v = fields.get(key)
        if v is not None and v != "":
            out.append(f"  {key}: {v}")
            emitted.add(key)
    for key, v in fields.items():
        if key not in emitted and key not in ("quotes", "id") and v not in (None, ""):
            out.append(f"  {key}: {v}")
    quotes = fields.get("quotes") or []
    if quotes:
        out.append("  source:")
        for q in quotes:
            out.append(f'    - quote: "{q.get("quote", "")}"')
            out.append(f'      at: "{q.get("at", "")}"')
            out.append(f'      speaker: {q.get("speaker", "")}')
    return "\n".join(out)


def render_file(chunks: list[dict]) -> str:
    """按 seq 顺序把 chunks 渲染回完整文件（prose 块原样带回 raw）。"""
    parts = []
    for c in chunks:
        if c["chunk_type"] == "prose":
            parts.append(c["fields"]["raw"])
        else:
            parts.append(render_item(c["ref_id"], c["fields"]))
    return "\n\n".join(parts) + "\n"


def compute_bump(old_chunks: list[dict], new_chunks: list[dict]) -> str:
    """按条目 ref_id 集合比较：删条目→major，增条目→minor，仅字段变→patch。"""
    old_map = {c["ref_id"]: c for c in old_chunks if c.get("ref_id")}
    new_map = {c["ref_id"]: c for c in new_chunks if c.get("ref_id")}
    if set(old_map) - set(new_map):
        return "major"
    if set(new_map) - set(old_map):
        return "minor"
    return "patch"


def next_ref_id(existing: list[str], prefix: str) -> str:
    """取该前缀历史最大编号 +1（调用方传入含历史版本在内的全部 ref_id，
    保证不复用已删编号）。"""
    mx = 0
    for rid in existing:
        m = re.match(rf"^{re.escape(prefix)}-(\d+)$", rid or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{prefix}-{mx + 1:02d}"


def bump_version(version: str, bump: str) -> str:
    """semver 推进：major 增 X.0.0，minor 增 x.Y.0，patch 增 x.y.Z。"""
    major, minor, patch = (int(p) for p in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
