"""会议记录模块测试：业务线/会议/上传、解析、块编辑 bump、导出/diff、搜索、分享。"""

from __future__ import annotations

import io
import zipfile

REQ_MD = """# 精准需求：测试会议_转写.md

## 会议概括

这是一次测试会议的概括段落。

## 需求清单

### 一、分组A

- id: REQ-01
  statement: 修正计划表分类错误
  status: confirmed
  confirm: B-01
  based_on: FACT-01
  source:
    - quote: "这个分类错了。"
      at: "10:25"
      speaker: 业务负责人1

### 二、分组B

- id: REQ-02
  statement: 计划表要带日期
  status: deferred
  source:
    - quote: "加一个日期。"
      at: "36:12"
      speaker: 开发者1

## 约束清单

- id: CON-01
  statement: 供应商表列名不要再改
  status: confirmed
  source:
    - quote: "名称不要多变。"
      at: "19:47"
      speaker: 开发者1

## 行动项清单

- id: ACT-01
  statement: 甲方会后发新版供应商表
  owner: 业务负责人1（英姐）
  status: confirmed
  source:
    - quote: "发在群里一份。"
      at: "21:07"
      speaker: 开发者1

## 覆盖校验

- [00:00–10:24] 无需求段（开场）
- [10:25–36:12] → REQ-01、REQ-02

## 待澄清Q

- id: Q-01
  question: 要货单捞取口径是否改为待处理的所有
  confirm: B-Q01
  suggest: 请甲方确认期望口径
  source:
    - quote: "处理待处理的所有。"
      at: "27:34"
      speaker: 业务负责人2
"""

FACT_MD = """# 业务事实：测试会议_转写.md

## 系统与渠道

- id: FACT-01
  statement: 计划表只是确认用，不代表自动下单
  category: 系统与渠道
  source:
    - quote: "只是拿给你确认用的。"
      at: "02:38"
      speaker: 开发者1

## 数据口径

- id: FACT-02
  statement: 补货参考口径是建议量大于0
  category: 数据口径
  source:
    - quote: "建议量大于0。"
      at: "26:59"
      speaker: 开发者1
    - quote: "没有，所有。"
      at: "27:07"
      speaker: 开发者1
  备注: 口径待系统核对
"""

BAD_REQ_MD = """# 精准需求：坏文件_转写.md

## 需求清单

- id: REQ-01
statement: 字段行没有缩进
"""

TRANSCRIPT_MD = """# 转写稿：测试会议

[00:00] 开发者1: 我们开始吧。
[00:30] 业务负责人1: 好的。
"""

OTHER_MD = "# 随手笔记\n\n不属于任何已知后缀的文件。\n"


def _mk_meeting(env, dir_name="260804-采购第5次业务交流", name="采购第5次业务交流"):
    client, human = env["client"], env["human"]
    r = client.post(
        "/api/v1/meeting-series",
        json={"project_id": env["project_id"], "name": "采购部分"},
        headers=human,
    )
    assert r.status_code == 201, r.text
    series_id = r.json()["id"]
    r = client.post(
        "/api/v1/meetings",
        json={"series_id": series_id, "name": name, "dir_name": dir_name},
        headers=human,
    )
    assert r.status_code == 201, r.text
    return series_id, r.json()


def _upload(client, human, meeting_id, files: dict[str, str]):
    return client.post(
        f"/api/v1/meetings/{meeting_id}/upload",
        files=[("files", (name, text.encode("utf-8"), "text/markdown")) for name, text in files.items()],
        headers=human,
    )


def _file_by_name(meeting_detail, filename):
    return next(f for f in meeting_detail["files"] if f["filename"] == filename)


# 1. 建业务线/会议、批量上传（6 类文件名 → kind 识别）、重复上传 409


def test_series_meeting_upload_and_kind_detection(env):
    client, human = env["client"], env["human"]
    series_id, meeting = _mk_meeting(env)
    assert meeting["date"] == "2026-08-04"  # 目录名 YYMMDD- 前缀自动解析

    files = {
        "采购第5次业务交流_转写.md": TRANSCRIPT_MD,
        "采购第5次业务交流_转写_精准需求.md": REQ_MD,
        "采购第5次业务交流_转写_业务事实.md": FACT_MD,
        "采购第5次业务交流_转写_需求确认单.md": "# 确认单\n\n正文。\n",
        "采购第5次业务交流_转写_内部问题清单.md": "# 问题清单\n\n正文。\n",
        "采购第5次业务交流_转写_修正词表.md": "# 词表\n\n翱像 → 翱象\n",
    }
    r = _upload(client, human, meeting["id"], files)
    assert r.status_code == 200, r.text
    kinds = {x["filename"]: x["kind"] for x in r.json()["results"]}
    assert kinds == {
        "采购第5次业务交流_转写.md": "transcript",
        "采购第5次业务交流_转写_精准需求.md": "requirements",
        "采购第5次业务交流_转写_业务事实.md": "facts",
        "采购第5次业务交流_转写_需求确认单.md": "confirm",
        "采购第5次业务交流_转写_内部问题清单.md": "questions",
        "采购第5次业务交流_转写_修正词表.md": "glossary",
    }
    assert all(x["status"] == "ok" for x in r.json()["results"])

    r = client.get("/api/v1/meeting-series", headers=human)
    tree = r.json()
    assert tree[0]["id"] == series_id
    assert tree[0]["meetings"][0]["file_count"] == 6

    # 重复上传同会议同文件名 → 409
    r = _upload(client, human, meeting["id"], {"采购第5次业务交流_转写_精准需求.md": REQ_MD})
    assert r.status_code == 409


def test_unknown_suffix_kind_other(env):
    _, meeting = _mk_meeting(env)
    r = _upload(env["client"], env["human"], meeting["id"], {"随手笔记.md": OTHER_MD})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["kind"] == "other"


def test_crlf_source_file_parses(env):
    """真实源文件是 CRLF 行尾（Windows 导出），parser 必须先规范化再解析。"""
    _, meeting = _mk_meeting(env)
    crlf = REQ_MD.replace("\n", "\r\n")
    r = _upload(env["client"], env["human"], meeting["id"], {"测试会议_转写_精准需求.md": crlf})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result
    assert result["chunk_count"] > 0


def test_gbk_mojibake_filename_recovered(env):
    """非浏览器客户端（中文 Windows 的 curl）按 GBK 编码文件名时被 latin-1
    解码成乱码，上传端点应还原，kind 识别仍命中。"""
    _, meeting = _mk_meeting(env)
    name = "测试会议_转写_精准需求.md"
    mojibake = name.encode("gbk").decode("latin-1")
    r = _upload(env["client"], env["human"], meeting["id"], {mojibake: REQ_MD})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["filename"] == name
    assert result["kind"] == "requirements" and result["parse_status"] == "ok"


def test_facts_intro_prose_tolerated(env):
    """真实业务事实文件变体：# 标题与首个 ## 分节之间有一行引言散文，
    应收为 prose 块而不是报格式错误。"""
    _, meeting = _mk_meeting(env)
    text = FACT_MD.replace(
        "## 系统与渠道",
        "从转写稿提取的业务事实库，每条钉死在逐字原文引用上。\n\n## 系统与渠道",
        1,
    )
    r = _upload(env["client"], env["human"], meeting["id"], {"测试会议_业务事实.md": text})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result

    fid = result["file_id"]
    f = env["client"].get(f"/api/v1/files/{fid}", headers=env["human"]).json()
    prose = [c for c in f["chunks"] if c["chunk_type"] == "prose"]
    assert any("引言" in c["fields"]["raw"] or "逐字原文引用" in c["fields"]["raw"] for c in prose)
    assert [c["ref_id"] for c in f["chunks"] if c["chunk_type"] == "fact"] == ["FACT-01", "FACT-02"]


def test_facts_without_sections_tolerated(env):
    """真实变体：业务事实文件没有 ## 分节标题，条目直接跟在标题后。
    条目自带 category 字段，应作为归属分节，不应报错。"""
    _, meeting = _mk_meeting(env)
    text = (
        "# 业务事实：无分节会议_转写.md\n\n"
        "- id: FACT-01\n"
        "  statement: 翱象和牵牛花是两个不同的采购平台\n"
        "  category: 系统与渠道\n"
        "  source:\n"
        '    - quote: "两个平台都要维护。"\n'
        '      at: "06:02"\n'
        "      speaker: 采购负责人\n"
    )
    r = _upload(env["client"], env["human"], meeting["id"], {"无分节会议_业务事实.md": text})
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result
    f = env["client"].get(f"/api/v1/files/{result['file_id']}", headers=env["human"]).json()
    fact = next(c for c in f["chunks"] if c["chunk_type"] == "fact")
    assert fact["section"] == "系统与渠道"
    assert fact["fields"]["category"] == "系统与渠道"


def test_facts_prose_section_and_meeting_field(env):
    """真实变体：facts 文件含 ## 会议概括 散文节、## 业务事实 总节，
    条目带 meeting: 字段。"""
    _, meeting = _mk_meeting(env)
    text = (
        "# 业务事实：变体会议_转写.md\n\n"
        "## 会议概括\n\n"
        "本次会议梳理了供应商管理表的字段含义。\n\n"
        "## 业务事实\n\n"
        "- id: FACT-01\n"
        "  statement: 1688线上和1688供应商是两种编码\n"
        "  category: 术语与别名\n"
        "  meeting: 9月9日供应商管理表系统对齐2\n"
        "  source:\n"
        '    - quote: "两种不同的编码。"\n'
        '      at: "05:53"\n'
        "      speaker: 开发者\n"
    )
    r = _upload(env["client"], env["human"], meeting["id"], {"变体会议_业务事实.md": text})
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result
    f = env["client"].get(f"/api/v1/files/{result['file_id']}", headers=env["human"]).json()
    fact = next(c for c in f["chunks"] if c["chunk_type"] == "fact")
    assert fact["fields"]["meeting"] == "9月9日供应商管理表系统对齐2"
    prose = [c for c in f["chunks"] if c["chunk_type"] == "prose"]
    assert any("会议概括" in c["fields"]["raw"] for c in prose)
    assert any("梳理了供应商管理表" in c["fields"]["raw"] for c in prose)


def test_requirements_real_world_variants(env):
    """真实变体合集：约束清单下的说明性散文、CON 条目混在 REQ 分节、
    条目以 ## REQ-01 xxx 为标题（无标准分节）、6 空格误缩进的 备注 字段、
    constraint 字段。"""
    _, meeting = _mk_meeting(env)
    text = (
        "# 精准需求：变体会议_转写.md\n\n"
        "## REQ-01 翱象供货关系模板导出两版\n\n"
        "- id: REQ-01\n"
        "  statement: 翱象供货关系导出支持两版\n"
        "  constraint: 覆盖翱象系统全部 41 万+ 供货关系\n"
        "  status: confirmed\n"
        "  source:\n"
        '    - quote: "导出两版。"\n'
        '      at: "10:00"\n'
        "      speaker: 开发者\n"
        "      备注: 此行标签疑误归属\n\n"
        "## 约束清单\n\n"
        "（本场无明确指向乙方的禁令/约束。）\n\n"
        "### 2. CON 约束\n\n"
        "- id: CON-01\n"
        "  statement: 字段枚举后续可按需追加\n"
        "  status: confirmed\n"
        "  source:\n"
        '    - quote: "可以追加。"\n'
        '      at: "11:00"\n'
        "      speaker: 开发者\n"
    )
    r = _upload(env["client"], env["human"], meeting["id"], {"变体会议_精准需求.md": text})
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result
    f = env["client"].get(f"/api/v1/files/{result['file_id']}", headers=env["human"]).json()
    items = {c["ref_id"]: c for c in f["chunks"] if c["chunk_type"] != "prose"}
    assert set(items) == {"REQ-01", "CON-01"}
    assert items["REQ-01"]["chunk_type"] == "req"
    assert items["REQ-01"]["fields"]["constraint"].startswith("覆盖翱象")
    assert items["REQ-01"]["fields"]["备注"] == "此行标签疑误归属"
    assert items["CON-01"]["chunk_type"] == "con"  # 类型由 id 前缀决定，不被分节带偏
    prose = [c for c in f["chunks"] if c["chunk_type"] == "prose"]
    assert any("本场无明确指向乙方" in c["fields"]["raw"] for c in prose)


def test_requirements_q_statement_and_deadline(env):
    """真实变体：Q 条目用 statement 承载问题（无 question 字段）、ACT 带 deadline。"""
    _, meeting = _mk_meeting(env)
    text = (
        "# 精准需求：变体会议2_转写.md\n\n"
        "## 待澄清Q\n\n"
        "- id: Q-01\n"
        '  statement: "备注"种类口径待确认\n'
        "  status: needs_clarification\n"
        "  source:\n"
        '    - quote: "这状态就是买不买嘛。"\n'
        '      at: "01:54"\n'
        "      speaker: 业务负责人\n\n"
        "## 行动项清单\n\n"
        "- id: ACT-01\n"
        "  statement: 开发者打包当前版本发给业务负责人\n"
        "  owner: 开发者小唐\n"
        "  deadline: 尽快（无明确截止日期）\n"
        "  status: confirmed\n"
        "  source:\n"
        '    - quote: "我打包一个发给你看一下。"\n'
        '      at: "31:22"\n'
        "      speaker: 开发者\n"
    )
    r = _upload(env["client"], env["human"], meeting["id"], {"变体会议2_精准需求.md": text})
    result = r.json()["results"][0]
    assert result["status"] == "ok" and result["parse_status"] == "ok", result
    f = env["client"].get(f"/api/v1/files/{result['file_id']}", headers=env["human"]).json()
    items = {c["ref_id"]: c for c in f["chunks"] if c["chunk_type"] != "prose"}
    assert items["Q-01"]["chunk_type"] == "q"
    assert items["Q-01"]["fields"]["statement"].startswith('"备注"种类') or "备注" in items["Q-01"]["fields"]["statement"]
    assert items["ACT-01"]["fields"]["deadline"] == "尽快（无明确截止日期）"


# 2. REQ/FACT 解析正确性


def test_parse_requirements_chunks(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"测试会议_转写_精准需求.md": REQ_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "测试会议_转写_精准需求.md")["id"]

    f = client.get(f"/api/v1/files/{fid}", headers=human).json()
    assert f["parse_status"] == "ok"
    chunks = f["chunks"]
    assert [c["seq"] for c in chunks] == list(range(len(chunks)))  # seq 连续有序

    items = [c for c in chunks if c["chunk_type"] != "prose"]
    assert [c["ref_id"] for c in items] == ["REQ-01", "REQ-02", "CON-01", "ACT-01", "Q-01"]
    assert [c["chunk_type"] for c in items] == ["req", "req", "con", "act", "q"]

    req01 = items[0]
    assert req01["section"] == "一、分组A"  ### 分组记进 section
    assert req01["fields"]["statement"] == "修正计划表分类错误"
    assert req01["fields"]["status"] == "confirmed"
    assert req01["fields"]["confirm"] == "B-01"
    assert req01["fields"]["based_on"] == "FACT-01"
    assert req01["fields"]["quotes"] == [
        {"quote": "这个分类错了。", "at": "10:25", "speaker": "业务负责人1"}
    ]
    assert "修正计划表分类错误" in req01["text_md"]

    act01 = items[3]
    assert act01["fields"]["owner"] == "业务负责人1（英姐）"
    q01 = items[4]
    assert q01["fields"]["question"] == "要货单捞取口径是否改为待处理的所有"
    assert q01["fields"]["suggest"] == "请甲方确认期望口径"

    # 散文节保留为 prose 块（标题行、会议概括、覆盖校验、清单标题、分组标题）
    prose = [c for c in chunks if c["chunk_type"] == "prose"]
    prose_text = "\n".join(c["text_md"] for c in prose)
    assert "这是一次测试会议的概括段落。" in prose_text
    assert "[10:25–36:12] → REQ-01、REQ-02" in prose_text
    assert "## 需求清单" in prose_text and "### 一、分组A" in prose_text


def test_parse_facts_chunks(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"测试会议_转写_业务事实.md": FACT_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "测试会议_转写_业务事实.md")["id"]
    chunks = client.get(f"/api/v1/files/{fid}", headers=human).json()["chunks"]

    facts = [c for c in chunks if c["chunk_type"] == "fact"]
    assert [c["ref_id"] for c in facts] == ["FACT-01", "FACT-02"]
    assert facts[0]["section"] == "系统与渠道"
    assert facts[0]["fields"]["category"] == "系统与渠道"
    assert "status" not in facts[0]["fields"]
    assert len(facts[1]["fields"]["quotes"]) == 2
    assert facts[1]["fields"]["备注"] == "口径待系统核对"


# 3. 解析失败 → failed + 报错含行号，不影响同批其他文件


def test_parse_failure_per_file(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    r = _upload(
        client, human, meeting["id"],
        {"坏文件_转写_精准需求.md": BAD_REQ_MD, "测试会议_转写_业务事实.md": FACT_MD},
    )
    assert r.status_code == 200, r.text
    results = {x["filename"]: x for x in r.json()["results"]}
    bad = results["坏文件_转写_精准需求.md"]
    assert bad["status"] == "failed"
    assert "坏文件_转写_精准需求.md" in bad["error"]  # 含文件名
    assert "第 6 行" in bad["error"]  # 含行号
    assert results["测试会议_转写_业务事实.md"]["status"] == "ok"

    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    bad_file = _file_by_name(detail, "坏文件_转写_精准需求.md")
    assert bad_file["parse_status"] == "failed"
    assert "第 6 行" in bad_file["parse_error"]

    # 解析失败的同名文件允许重传覆盖
    r = _upload(client, human, meeting["id"], {"坏文件_转写_精准需求.md": REQ_MD})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "ok"


# 4. 块编辑 bump 规则 + 非切块文件手选 bump


def _get_chunks(client, human, fid):
    return client.get(f"/api/v1/files/{fid}", headers=human).json()["chunks"]


def _put_chunks(client, human, fid, chunks, change_note=""):
    body = {
        "chunks": [
            {"ref_id": c["ref_id"], "chunk_type": c["chunk_type"],
             "section": c["section"], "fields": c["fields"]}
            for c in chunks
        ],
        "change_note": change_note,
    }
    return client.put(f"/api/v1/files/{fid}/chunks", json=body, headers=human)


def test_chunk_edit_bump_rules(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"测试会议_转写_精准需求.md": REQ_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "测试会议_转写_精准需求.md")["id"]

    f = client.get(f"/api/v1/files/{fid}", headers=human).json()
    assert f["current_version"] == "1.0.0"
    assert f["versions"][0]["source"] == "upload" and f["versions"][0]["bump"] == "none"

    # 删条目 → MAJOR（1.0.0 → 2.0.0）
    chunks = [c for c in _get_chunks(client, human, fid) if c["ref_id"] != "REQ-02"]
    r = _put_chunks(client, human, fid, chunks)
    assert r.status_code == 200, r.text
    assert r.json()["bump"] == "major" and r.json()["version"] == "2.0.0"

    # 增条目 → MINOR（2.0.0 → 2.1.0）；新 ref_id 不复用已删的 REQ-02
    chunks = _get_chunks(client, human, fid)
    chunks.append({
        "ref_id": None, "chunk_type": "req", "section": "一、分组A",
        "fields": {"statement": "新增的需求条目", "status": "confirmed"},
    })
    r = _put_chunks(client, human, fid, chunks)
    assert r.status_code == 200, r.text
    assert r.json()["bump"] == "minor" and r.json()["version"] == "2.1.0"
    new_ids = [c["ref_id"] for c in _get_chunks(client, human, fid) if c["chunk_type"] == "req"]
    assert "REQ-03" in new_ids  # REQ-02 已删但编号不复用

    # 仅改字段 → PATCH（2.1.0 → 2.1.1）；quotes 不提交时从旧块继承
    chunks = _get_chunks(client, human, fid)
    for c in chunks:
        if c["ref_id"] == "REQ-01":
            c["fields"] = {"statement": "修正计划表分类错误（已改）", "status": "confirmed"}
    r = _put_chunks(client, human, fid, chunks)
    assert r.status_code == 200, r.text
    assert r.json()["bump"] == "patch" and r.json()["version"] == "2.1.1"
    req01 = next(c for c in _get_chunks(client, human, fid) if c["ref_id"] == "REQ-01")
    assert req01["fields"]["statement"] == "修正计划表分类错误（已改）"
    assert req01["fields"]["quotes"] == [
        {"quote": "这个分类错了。", "at": "10:25", "speaker": "业务负责人1"}
    ]


def test_content_edit_manual_bump(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"测试会议_转写.md": TRANSCRIPT_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "测试会议_转写.md")["id"]

    f = client.get(f"/api/v1/files/{fid}", headers=human).json()
    assert f["parse_status"] == "na" and f["chunks"] == []

    # 切块端点对非切块文件 409，反之亦然
    r = _put_chunks(client, human, fid, [])
    assert r.status_code == 409
    r = client.put(
        f"/api/v1/files/{fid}/content",
        json={"content": TRANSCRIPT_MD + "\n[01:00] 开发者1: 补充一句。\n", "bump": "minor"},
        headers=human,
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.1.0" and r.json()["bump"] == "minor"

    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    req_fid = None
    _upload(client, human, meeting["id"], {"测试会议_转写_精准需求.md": REQ_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    req_fid = _file_by_name(detail, "测试会议_转写_精准需求.md")["id"]
    r = client.put(
        f"/api/v1/files/{req_fid}/content", json={"content": "x", "bump": "patch"}, headers=human
    )
    assert r.status_code == 409  # 切块文件必须走 /chunks


# 5. 导出与 diff


def test_export_and_diff(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"测试会议_转写_精准需求.md": REQ_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "测试会议_转写_精准需求.md")["id"]

    # 未编辑时单文件导出 = 上传原文
    r = client.get(f"/api/v1/files/{fid}/export", headers=human)
    assert r.status_code == 200
    assert r.text == REQ_MD
    assert "attachment" in r.headers["content-disposition"]
    assert "filename*=UTF-8''" in r.headers["content-disposition"]  # RFC 5987 中文名

    # 改一条字段造出 1.0.1
    chunks = _get_chunks(client, human, fid)
    for c in chunks:
        if c["ref_id"] == "REQ-02":
            c["fields"]["statement"] = "计划表要带日期和星期"
    r = _put_chunks(client, human, fid, chunks)
    assert r.json()["version"] == "1.0.1"

    r = client.get(f"/api/v1/files/{fid}/diff", params={"from": "1.0.0", "to": "1.0.1"}, headers=human)
    diff = r.json()["diff"]
    assert diff.startswith("---") and "+++" in diff.splitlines()[1]
    assert "-  statement: 计划表要带日期" in diff
    assert "+  statement: 计划表要带日期和星期" in diff

    r = client.get(
        f"/api/v1/files/{fid}/diff",
        params={"from": "1.0.0", "to": "1.0.1", "download": 1},
        headers=human,
    )
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]

    # 历史版本可读
    v1 = client.get(f"/api/v1/files/{fid}/versions/1.0.0", headers=human).json()
    assert v1["content_md"] == REQ_MD

    # 整会议 zip（带 diff 日志）
    r = client.get(f"/api/v1/meetings/{meeting['id']}/export?with_diffs=1", headers=human)
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "测试会议_转写_精准需求.md" in names
    assert any(n.startswith("diffs/") and "1.0.0-1.0.1" in n for n in names)


# 6. 搜索


def test_search(env):
    client, human = env["client"], env["human"]
    series_id, meeting = _mk_meeting(env)
    _upload(
        client, human, meeting["id"],
        {"测试会议_转写_精准需求.md": REQ_MD, "测试会议_转写_业务事实.md": FACT_MD},
    )

    r = client.get("/api/v1/meetings/search", params={"q": "计划表"}, headers=human)
    hits = r.json()
    assert hits and all("计划表" in h["text_md"] for h in hits)
    h = hits[0]
    assert h["meeting_id"] == meeting["id"] and h["meeting_name"] == "采购第5次业务交流"
    assert h["filename"] and h["file_id"]  # 定位信息

    r = client.get("/api/v1/meetings/search", params={"kind": "fact"}, headers=human)
    assert {h["chunk_type"] for h in r.json()} == {"fact"}

    r = client.get("/api/v1/meetings/search", params={"kind": "req", "status": "deferred"}, headers=human)
    assert [h["ref_id"] for h in r.json()] == ["REQ-02"]

    # 业务线过滤：另一个 series 的会议不命中
    r2 = client.post(
        "/api/v1/meeting-series",
        json={"project_id": env["project_id"], "name": "运营部分"},
        headers=human,
    )
    r = client.get("/api/v1/meetings/search", params={"series_id": r2.json()["id"]}, headers=human)
    assert r.json() == []
    r = client.get("/api/v1/meetings/search", params={"series_id": series_id}, headers=human)
    assert len(r.json()) > 0


# 7. 分享


def test_share(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(
        client, human, meeting["id"],
        {
            "测试会议_转写_精准需求.md": REQ_MD,
            "测试会议_转写_业务事实.md": FACT_MD,
            "测试会议_转写.md": TRANSCRIPT_MD,
        },
    )
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    token = detail["share_token"]
    assert token.startswith("mt-")

    # 无鉴权可读，默认范围 requirements+facts+confirm（不含转写稿）
    r = client.get(f"/api/share/{token}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "修正计划表分类错误" in r.text
    assert "计划表只是确认用" in r.text
    assert "我们开始吧" not in r.text  # transcript 不在默认范围

    # ?kinds= 临时覆盖
    r = client.get(f"/api/share/{token}", params={"kinds": "transcript"})
    assert "我们开始吧" in r.text and "修正计划表分类错误" not in r.text

    # 无 token / 错误 token → 404
    assert client.get("/api/share/mt-deadbeef").status_code == 404

    # 会议内搜索
    r = client.get(f"/api/share/{token}/search", params={"q": "建议量大于0", "kind": "fact"})
    hits = r.json()
    assert len(hits) == 1 and hits[0]["ref_id"] == "FACT-02"
    assert hits[0]["meeting_id"] == meeting["id"]

    # share_kinds 勾选生效
    r = client.put(f"/api/v1/meetings/{meeting['id']}/share-kinds",
                   json={"kinds": ["facts"]}, headers=human)
    assert r.status_code == 200
    r = client.get(f"/api/share/{token}")
    assert "计划表只是确认用" in r.text and "修正计划表分类错误" not in r.text
    r = client.put(f"/api/v1/meetings/{meeting['id']}/share-kinds",
                   json={"kinds": ["bogus"]}, headers=human)
    assert r.status_code == 422

    # regenerate 后旧码失效、新码可读
    r = client.post(f"/api/v1/meetings/{meeting['id']}/share-token/regenerate", headers=human)
    assert r.status_code == 200
    new_token = r.json()["share_token"]
    assert new_token != token
    assert client.get(f"/api/share/{token}").status_code == 404
    assert client.get(f"/api/share/{new_token}").status_code == 200


def test_agent_key_forbidden_on_admin(env):
    """agent key 对会议 admin 端点 403；分享端点无需 key。"""
    client = env["client"]
    r = client.post(
        "/api/v1/meeting-series",
        json={"project_id": env["project_id"], "name": "采购部分"},
        headers=env["agent"],
    )
    assert r.status_code == 403
    r = client.get("/api/v1/meeting-series", headers=env["agent"])
    assert r.status_code == 403
    r = client.get("/api/v1/meetings/search", headers=env["agent"])
    assert r.status_code == 403


# 8. 命名识别放宽（无 _转写 中缀 + _精简 派生）与文件维护端点


def test_kind_detection_without_transcript_infix(env):
    """真实库命名（无 _转写 中缀）与 _精简 派生文件的 kind 识别。"""
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    files = {
        "采购第一次业务交流_精准需求.md": REQ_MD,
        "采购第一次业务交流_业务事实.md": FACT_MD,
        "采购第一次业务交流_需求确认单.md": "# 确认单\n\n正文。\n",
        "采购第一次业务交流_内部问题清单.md": "# 问题清单\n\n正文。\n",
        "采购第一次业务交流_修正词表.md": "# 词表\n\n正文。\n",
        "采购第一次业务交流_转写.md": TRANSCRIPT_MD,
        "采购第一次业务交流_精准需求_精简.md": "# 精简\n\n正文。\n",
        "采购第一次业务交流_业务事实_精简.md": "# 精简\n\n正文。\n",
    }
    r = _upload(client, human, meeting["id"], files)
    assert r.status_code == 200, r.text
    kinds = {x["filename"]: x["kind"] for x in r.json()["results"]}
    assert kinds == {
        "采购第一次业务交流_精准需求.md": "requirements",
        "采购第一次业务交流_业务事实.md": "facts",
        "采购第一次业务交流_需求确认单.md": "confirm",
        "采购第一次业务交流_内部问题清单.md": "questions",
        "采购第一次业务交流_修正词表.md": "glossary",
        "采购第一次业务交流_转写.md": "transcript",
        "采购第一次业务交流_精准需求_精简.md": "other",
        "采购第一次业务交流_业务事实_精简.md": "other",
    }
    # 无中缀的精准需求同样切块成功
    req_result = next(
        x for x in r.json()["results"] if x["filename"] == "采购第一次业务交流_精准需求.md"
    )
    assert req_result["parse_status"] == "ok" and req_result["chunk_count"] > 0


def test_meeting_explicit_date(env):
    """建会议显式传 date 优先于目录名解析；留空仍走目录名。"""
    client, human = env["client"], env["human"]
    series_id, _ = _mk_meeting(env)
    r = client.post(
        "/api/v1/meetings",
        json={"series_id": series_id, "name": "采购第6次业务交流",
              "dir_name": "260811-采购第6次业务交流", "date": "2026-08-20"},
        headers=human,
    )
    assert r.status_code == 201 and r.json()["date"] == "2026-08-20"
    r = client.post(
        "/api/v1/meetings",
        json={"series_id": series_id, "name": "采购第7次业务交流", "date": "20260820"},
        headers=human,
    )
    assert r.status_code == 422


def test_reparse_and_rename_rekind(env):
    """reparse 挽救存量（other → 改名后重识别为切块类）；改名后 kind 重识别，
    解析失败路径清空 chunks 并给出含行号的报错。"""
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    r = _upload(client, human, meeting["id"], {"会议笔记.md": REQ_MD})
    fid = r.json()["results"][0]["file_id"]
    assert r.json()["results"][0]["kind"] == "other"

    # reparse：文件名不变，kind 仍是 other → na、无 chunks
    r = client.post(f"/api/v1/files/{fid}/reparse", headers=human)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "other" and r.json()["parse_status"] == "na"

    # 改名带 _精准需求 后缀 → kind 重识别 + 自动 reparse 出 chunks
    r = client.patch(f"/api/v1/files/{fid}", json={"filename": "会议笔记_精准需求.md"}, headers=human)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "requirements" and r.json()["parse_status"] == "ok"
    assert r.json()["chunk_count"] > 0
    chunks = _get_chunks(client, human, fid)
    assert any(c["ref_id"] == "REQ-01" for c in chunks)

    # 改成 _业务事实：REQ 内容按 FACT 规则解析失败 → failed + 行号 + chunks 清空
    # （facts parser 现在容忍散文节，错误推迟到第一条 REQ 条目所在行）
    r = client.patch(f"/api/v1/files/{fid}", json={"filename": "会议笔记_业务事实.md"}, headers=human)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "facts" and r.json()["parse_status"] == "failed"
    assert "第 11 行" in r.json()["parse_error"] and "FACT" in r.json()["parse_error"]
    assert _get_chunks(client, human, fid) == []

    # 改回 _精准需求 → 恢复 ok；不产生新版本（chunks 是 content 派生物）
    r = client.patch(f"/api/v1/files/{fid}", json={"filename": "会议笔记_精准需求.md"}, headers=human)
    assert r.json()["parse_status"] == "ok"
    f = client.get(f"/api/v1/files/{fid}", headers=human).json()
    assert f["current_version"] == "1.0.0" and len(f["versions"]) == 1


def test_rename_conflict(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    _upload(client, human, meeting["id"], {"a_精准需求.md": REQ_MD, "b_业务事实.md": FACT_MD})
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    fid = _file_by_name(detail, "a_精准需求.md")["id"]
    r = client.patch(f"/api/v1/files/{fid}", json={"filename": "b_业务事实.md"}, headers=human)
    assert r.status_code == 409


def test_delete_file(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    r = _upload(client, human, meeting["id"], {"a_精准需求.md": REQ_MD})
    fid = r.json()["results"][0]["file_id"]

    r = client.delete(f"/api/v1/files/{fid}", headers=human)
    assert r.status_code == 204
    # 文件、版本、chunks 连带删除
    assert client.get(f"/api/v1/files/{fid}", headers=human).status_code == 404
    assert client.get(f"/api/v1/files/{fid}/versions/1.0.0", headers=human).status_code == 404
    detail = client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).json()
    assert detail["files"] == []
    # agent key 删除 → 403
    assert client.delete(f"/api/v1/files/999", headers=env["agent"]).status_code == 403


# 9. 会议本身可修改、可删除


def test_update_meeting(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)  # date 由目录名解析为 2026-08-04
    mid = meeting["id"]

    # 改名称与目录名
    r = client.patch(
        f"/api/v1/meetings/{mid}",
        json={"name": "采购第5次业务交流（改）", "dir_name": "260804-采购第5次业务交流-改"},
        headers=human,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "采购第5次业务交流（改）"
    assert r.json()["date"] == "2026-08-04"  # 未传 date → 保持不变

    # 改日期
    r = client.patch(f"/api/v1/meetings/{mid}", json={"date": "2026-08-13"}, headers=human)
    assert r.json()["date"] == "2026-08-13"

    # 显式 null 清空日期
    r = client.patch(f"/api/v1/meetings/{mid}", json={"date": None}, headers=human)
    assert r.json()["date"] is None

    # 非法日期 422；空名称 422
    assert client.patch(f"/api/v1/meetings/{mid}", json={"date": "20260813"}, headers=human).status_code == 422
    assert client.patch(f"/api/v1/meetings/{mid}", json={"name": "  "}, headers=human).status_code == 422

    # agent key → 403
    assert client.patch(f"/api/v1/meetings/{mid}", json={"name": "x"}, headers=env["agent"]).status_code == 403


def test_delete_meeting(env):
    client, human = env["client"], env["human"]
    _, meeting = _mk_meeting(env)
    mid = meeting["id"]
    r = _upload(client, human, meeting["id"], {"a_精准需求.md": REQ_MD})
    fid = r.json()["results"][0]["file_id"]

    # agent key → 403
    assert client.delete(f"/api/v1/meetings/{mid}", headers=env["agent"]).status_code == 403

    r = client.delete(f"/api/v1/meetings/{mid}", headers=human)
    assert r.status_code == 204

    # 会议、文件、版本、chunks 全部查不到
    assert client.get(f"/api/v1/meetings/{mid}", headers=human).status_code == 404
    assert client.get(f"/api/v1/files/{fid}", headers=human).status_code == 404
    assert client.get(f"/api/v1/files/{fid}/versions/1.0.0", headers=human).status_code == 404
    hits = client.get("/api/v1/meetings/search", params={"q": "计划表"}, headers=human).json()
    assert [h for h in hits if h["meeting_id"] == mid] == []

    # 业务线树里也不再出现该会议
    tree = client.get("/api/v1/meeting-series", headers=human).json()
    assert all(m["id"] != mid for s in tree for m in s["meetings"])


def test_project_delete_blocked_by_meeting_series(env):
    """项目下有会议业务线时，删除项目应 409（会议记录不随项目级联删除）。"""
    client, human = env["client"], env["human"]
    # 用独立项目（env 默认项目因绑定唯一 human key 会先被 key 守卫拦截）
    r = client.post("/api/v1/projects", json={"name": "会议隔离测试项目"}, headers=human)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post("/api/v1/meeting-series", json={"project_id": pid, "name": "采购部分"}, headers=human)
    assert r.status_code == 201, r.text
    series_id = r.json()["id"]
    r = client.post("/api/v1/meetings", json={"series_id": series_id, "name": "测试会议"}, headers=human)
    assert r.status_code == 201, r.text

    r = client.delete(f"/api/v1/projects/{pid}", headers=human)
    assert r.status_code == 409
    assert "会议" in r.json()["detail"]

    # 删掉业务线后即可删除项目
    r = client.delete(f"/api/v1/meeting-series/{series_id}", headers=human)
    assert r.status_code == 204  # 级联删除其下会议/文件/版本/chunks

    # 业务线树已空
    assert client.get("/api/v1/meeting-series", headers=human).json() == []
    r = client.delete(f"/api/v1/projects/{pid}", headers=human)
    assert r.status_code == 200


# 10. 业务线删除（级联）与项目删除的 409 守卫


def test_delete_meeting_series_cascade(env):
    client, human = env["client"], env["human"]
    series_id, meeting = _mk_meeting(env)
    r = _upload(client, human, meeting["id"], {"a_精准需求.md": REQ_MD})
    fid = r.json()["results"][0]["file_id"]

    # agent key → 403
    assert client.delete(f"/api/v1/meeting-series/{series_id}", headers=env["agent"]).status_code == 403

    r = client.delete(f"/api/v1/meeting-series/{series_id}", headers=human)
    assert r.status_code == 204

    # 业务线 / 会议 / 文件 / 版本 / chunks 全部查不到
    assert client.get("/api/v1/meeting-series", headers=human).json() == []
    assert client.get(f"/api/v1/meetings/{meeting['id']}", headers=human).status_code == 404
    assert client.get(f"/api/v1/files/{fid}", headers=human).status_code == 404
    assert client.get(f"/api/v1/files/{fid}/versions/1.0.0", headers=human).status_code == 404
    hits = client.get("/api/v1/meetings/search", params={"q": "计划表"}, headers=human).json()
    assert hits == []

    # 不存在的业务线 → 404
    assert client.delete(f"/api/v1/meeting-series/{series_id}", headers=human).status_code == 404


def test_delete_project_blocked_by_meeting_series(env):
    """项目下有会议业务线时删除项目 → 409（先去会议记录里删业务线）。"""
    client, human = env["client"], env["human"]
    # 用独立项目（env 自带项目绑着唯一一把 human key，删它会先撞 human key 守卫）
    r = client.post("/api/v1/projects", json={"name": "会议项目"}, headers=human)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post(
        "/api/v1/meeting-series", json={"project_id": pid, "name": "采购部分"}, headers=human
    )
    assert r.status_code == 201, r.text
    series_id = r.json()["id"]

    r = client.delete(f"/api/v1/projects/{pid}", headers=human)
    assert r.status_code == 409
    assert "会议业务线" in r.json()["detail"]

    # 删掉业务线后项目可正常删除
    assert client.delete(f"/api/v1/meeting-series/{series_id}", headers=human).status_code == 204
    r = client.delete(f"/api/v1/projects/{pid}", headers=human)
    assert r.status_code == 200, r.text


# 11. 业务线汇总文档（总精准需求 / 总业务事实）


def _mk_series_with_two_meetings(env):
    """一个业务线下两个会议，各传一份 REQ + FACT，返回 (series_id, [meeting_ids], [req_file_ids])。"""
    client, human = env["client"], env["human"]
    r = client.post(
        "/api/v1/meeting-series",
        json={"project_id": env["project_id"], "name": "采购部分"},
        headers=human,
    )
    series_id = r.json()["id"]
    meeting_ids, req_fids = [], []
    for name in ("采购第1次业务交流", "采购第2次业务交流"):
        r = client.post("/api/v1/meetings",
                        json={"series_id": series_id, "name": name}, headers=human)
        mid = r.json()["id"]
        meeting_ids.append(mid)
        r = _upload(client, human, mid, {
            f"{name}_精准需求.md": REQ_MD, f"{name}_业务事实.md": FACT_MD,
        })
        assert r.status_code == 200, r.text
        req_fids.append(next(x["file_id"] for x in r.json()["results"]
                             if x["filename"].endswith("_精准需求.md")))
    return series_id, meeting_ids, req_fids


def _refresh(client, human, series_id):
    r = client.post(f"/api/v1/meeting-series/{series_id}/refresh-docs", headers=human)
    assert r.status_code == 200, r.text
    return r.json()["docs"]


def _get_doc(client, human, series_id, kind):
    detail = client.get(f"/api/v1/meeting-series/{series_id}", headers=human).json()
    doc = next(d for d in detail["docs"] if d["kind"] == kind)
    return client.get(f"/api/v1/series-docs/{doc['id']}", headers=human).json()


def _put_items(client, human, doc, items, change_note=""):
    return client.put(
        f"/api/v1/series-docs/{doc['id']}/items",
        json={"items": [
            {"ref_id": i["ref_id"], "chunk_type": i["chunk_type"],
             "section": i["section"], "fields": i["fields"]}
            for i in items
        ], "change_note": change_note},
        headers=human,
    )


def test_refresh_aggregates_with_origin(env):
    client, human = env["client"], env["human"]
    series_id, mids, _ = _mk_series_with_two_meetings(env)
    docs = _refresh(client, human, series_id)
    req_result = next(d for d in docs if d["kind"] == "requirements")
    fact_result = next(d for d in docs if d["kind"] == "facts")
    assert req_result["added"] == 10 and req_result["version"] == "1.0.0"  # 5 条目 × 2 会议
    assert fact_result["added"] == 4  # 2 FACT × 2 会议

    doc = _get_doc(client, human, series_id, "requirements")
    items = [i for i in doc["items"] if i["chunk_type"] != "prose"]
    ref_ids = [i["ref_id"] for i in items]
    assert len(ref_ids) == len(set(ref_ids))  # 重编号无冲突
    assert ref_ids[:5] == ["REQ-01", "REQ-02", "CON-01", "ACT-01", "Q-01"]
    assert ref_ids[5:] == ["REQ-03", "REQ-04", "CON-02", "ACT-02", "Q-02"]
    # 溯源字段
    first = items[0]
    assert first["origin_chunk_id"] and first["origin_meeting_id"] == mids[0]
    assert first["origin_ref_id"] == "REQ-01"
    assert first["origin_meeting_name"] == "采购第1次业务交流"
    assert first["origin_label"] == "采购第1次业务交流 · REQ-01"
    assert items[5]["origin_meeting_name"] == "采购第2次业务交流"


def test_refresh_idempotent_and_preserves_edits(env):
    client, human = env["client"], env["human"]
    series_id, mids, req_fids = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)

    # 幂等：二次 refresh 无新增、不产生新版本
    docs = _refresh(client, human, series_id)
    assert all(d["added"] == 0 for d in docs)
    doc = _get_doc(client, human, series_id, "requirements")
    assert len(doc["versions"]) == 1 and doc["current_version"] == "1.0.0"

    # 人工改汇总条目 statement
    items = doc["items"]
    items[0]["fields"]["statement"] = "人工改写后的陈述"
    r = _put_items(client, human, doc, items)
    assert r.status_code == 200, r.text

    # 源会议新增一条 REQ，再 refresh：只追加，不动已编辑条目
    fid = req_fids[0]
    chunks = _get_chunks(client, human, fid)
    chunks.append({
        "ref_id": None, "chunk_type": "req", "section": "一、分组A",
        "fields": {"statement": "源会议新增的需求", "status": "confirmed"},
    })
    r = _put_chunks(client, human, fid, chunks)
    assert r.status_code == 200, r.text
    docs = _refresh(client, human, series_id)
    req_result = next(d for d in docs if d["kind"] == "requirements")
    assert req_result["added"] == 1 and req_result["version"] == "1.1.0"

    doc = _get_doc(client, human, series_id, "requirements")
    by_stmt = {i["fields"].get("statement"): i for i in doc["items"]}
    assert "人工改写后的陈述" in by_stmt  # 人工编辑未被 refresh 覆盖
    assert "源会议新增的需求" in by_stmt
    assert by_stmt["源会议新增的需求"]["origin_ref_id"] == "REQ-03"


def test_link_update_propagates_to_source(env):
    client, human = env["client"], env["human"]
    series_id, _, req_fids = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)
    doc = _get_doc(client, human, series_id, "requirements")

    items = doc["items"]
    target = next(i for i in items if i["ref_id"] == "REQ-01")
    target["fields"]["statement"] = "汇总侧修正：计划表分类错误"
    r = _put_items(client, human, doc, items)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bump"] == "patch" and body["version"] == "1.0.1"
    link = next(l for l in body["links"] if l["ref_id"] == "REQ-01")
    assert link["action"] == "updated"
    assert link["source_file"] == "采购第1次业务交流_精准需求.md"
    assert link["source_version"] == "1.0.1"  # 源文件 patch bump

    # 源文件 chunks 同步
    src_chunks = _get_chunks(client, human, req_fids[0])
    src_req01 = next(c for c in src_chunks if c["ref_id"] == "REQ-01")
    assert src_req01["fields"]["statement"] == "汇总侧修正：计划表分类错误"
    assert src_req01["fields"]["quotes"]  # quotes 不动
    f = client.get(f"/api/v1/files/{req_fids[0]}", headers=human).json()
    assert f["current_version"] == "1.0.1"
    assert "汇总侧修正" in f["content_md"]  # content 已重新渲染

    # 联动后 origin_chunk_id 跟随重写后的新块（再次联动仍有效）
    doc = _get_doc(client, human, series_id, "requirements")
    t2 = next(i for i in doc["items"] if i["ref_id"] == "REQ-01")
    t2["fields"]["statement"] = "第二次联动改"
    r = _put_items(client, human, doc, doc["items"])
    assert r.status_code == 200, r.text
    src_chunks = _get_chunks(client, human, req_fids[0])
    assert next(c for c in src_chunks if c["ref_id"] == "REQ-01")["fields"]["statement"] == "第二次联动改"


def test_link_delete_propagates_and_missing_source(env):
    client, human = env["client"], env["human"]
    series_id, _, req_fids = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)
    doc = _get_doc(client, human, series_id, "requirements")

    # 删有来源条目 → 源块消失 + 源文件 major bump
    items = [i for i in doc["items"] if i["ref_id"] != "REQ-01"]
    r = _put_items(client, human, doc, items)
    body = r.json()
    assert body["bump"] == "major" and body["version"] == "2.0.0"
    link = next(l for l in body["links"] if l["ref_id"] == "REQ-01")
    assert link["action"] == "deleted" and link["source_version"] == "2.0.0"
    src_chunks = _get_chunks(client, human, req_fids[0])
    assert all(c["ref_id"] != "REQ-01" for c in src_chunks)
    f = client.get(f"/api/v1/files/{req_fids[0]}", headers=human).json()
    assert f["current_version"] == "2.0.0"

    # 源文件整个删掉后，再删汇总条目 → 只删汇总，标注「源已不存在」
    assert client.delete(f"/api/v1/files/{req_fids[1]}", headers=human).status_code == 204
    doc = _get_doc(client, human, series_id, "requirements")
    orphan = next(i for i in doc["items"] if i["origin_meeting_name"] == "采购第2次业务交流")
    items = [i for i in doc["items"] if i["ref_id"] != orphan["ref_id"]]
    r = _put_items(client, human, doc, items)
    link = next(l for l in r.json()["links"] if l["ref_id"] == orphan["ref_id"])
    assert link["action"] == "deleted" and link["source_file"] == "源已不存在"
    assert link["source_version"] is None


def test_add_business_level_item_and_export(env):
    client, human = env["client"], env["human"]
    series_id, _, _ = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)
    doc = _get_doc(client, human, series_id, "requirements")

    items = doc["items"]
    items.append({
        "ref_id": None, "chunk_type": "req", "section": "",
        "fields": {"statement": "业务级新增的跨会议需求", "status": "confirmed"},
    })
    r = _put_items(client, human, doc, items)
    assert r.status_code == 200, r.text
    assert r.json()["bump"] == "minor"
    added = next(l for l in r.json()["links"] if l["action"] == "added")
    assert added["origin"] == "业务级增加"

    doc = _get_doc(client, human, series_id, "requirements")
    new_item = next(i for i in doc["items"] if i["fields"].get("statement") == "业务级新增的跨会议需求")
    assert new_item["ref_id"] == "REQ-05"  # REQ-01..04 已占用
    assert new_item["origin_chunk_id"] is None
    assert new_item["origin_label"] == "业务级增加"

    # 导出：含来源行（溯源 + 业务级增加），来源不进 fields_json
    r = client.get(f"/api/v1/series-docs/{doc['id']}/export", headers=human)
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    text = r.text
    assert text.startswith("# 采购部分 · 总精准需求")
    assert "  来源: 采购第1次业务交流 · REQ-01" in text
    assert "  来源: 业务级增加" in text
    assert "来源" not in new_item["fields"]  # 数据保持干净


def test_series_share_token(env):
    client, human = env["client"], env["human"]
    series_id, mids, _ = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)
    detail = client.get(f"/api/v1/meeting-series/{series_id}", headers=human).json()
    token = detail["share_token"]
    assert token.startswith("ms-")

    # ms- token 可读：含两个汇总文档与来源行
    r = client.get(f"/api/share/{token}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "总精准需求" in r.text and "总业务事实" in r.text
    assert "来源: 采购第1次业务交流 · REQ-01" in r.text

    # regenerate 旧码失效、新码可读
    r = client.post(f"/api/v1/meeting-series/{series_id}/share-token/regenerate", headers=human)
    new_token = r.json()["share_token"]
    assert new_token != token
    assert client.get(f"/api/share/{token}").status_code == 404
    assert client.get(f"/api/share/{new_token}").status_code == 200

    # mt- 会议 token 不受影响的回归
    m_detail = client.get(f"/api/v1/meetings/{mids[0]}", headers=human).json()
    mt = m_detail["share_token"]
    r = client.get(f"/api/share/{mt}")
    assert r.status_code == 200 and "修正计划表分类错误" in r.text


def test_series_docs_agent_forbidden(env):
    client, human = env["client"], env["human"]
    series_id, _, _ = _mk_series_with_two_meetings(env)
    _refresh(client, human, series_id)
    detail = client.get(f"/api/v1/meeting-series/{series_id}", headers=human).json()
    doc_id = detail["docs"][0]["id"]
    agent = env["agent"]
    assert client.get(f"/api/v1/meeting-series/{series_id}", headers=agent).status_code == 403
    assert client.post(f"/api/v1/meeting-series/{series_id}/refresh-docs", headers=agent).status_code == 403
    assert client.post(f"/api/v1/meeting-series/{series_id}/share-token/regenerate", headers=agent).status_code == 403
    assert client.get(f"/api/v1/series-docs/{doc_id}", headers=agent).status_code == 403
    assert client.put(f"/api/v1/series-docs/{doc_id}/items", json={"items": []}, headers=agent).status_code == 403
    assert client.get(f"/api/v1/series-docs/{doc_id}/export", headers=agent).status_code == 403
