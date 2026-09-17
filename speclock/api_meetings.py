"""会议记录 API：admin_router（写，human key）+ share_router（哈希码公开只读）。

- admin_router 挂在 /api/v1 下，与 api_admin 同一边界：全部端点 require_human；
- share_router 挂在 /api/share 下，无 API key——share_token 本身即授权
  （mt- 前缀，明文存库，可随时 regenerate 使旧码失效）。

版本语义：上传即 v1=1.0.0（content_md 存上传原文）；切块文件走 PUT chunks
（全量提交），compute_bump 自动算 major/minor/patch，新版本内容为渲染产物；
非切块文件走 PUT content，用户手选 bump。
"""

from __future__ import annotations

import difflib
import io
import json
import re
import secrets
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from speclock import meeting_parsing as mp
from speclock.auth import audit, require_human
from speclock.db import get_db
from speclock.models import (
    ApiKey,
    Meeting,
    MeetingChunk,
    MeetingFile,
    MeetingFileVersion,
    MeetingSeries,
    Project,
    SeriesDoc,
    SeriesDocVersion,
    SeriesItem,
)
from speclock.schemas import (
    ChunkUpdate,
    ContentUpdate,
    FileRename,
    MeetingCreate,
    MeetingSeriesCreate,
    MeetingUpdate,
    SeriesItemsUpdate,
    ShareKindsUpdate,
)

admin_router = APIRouter(
    prefix="/api/v1",
    tags=["meetings-admin"],
    dependencies=[Depends(require_human)],
)
share_router = APIRouter(prefix="/api/share", tags=["meetings-share"])

KIND_LABELS = {
    "requirements": "精准需求",
    "facts": "业务事实",
    "confirm": "需求确认单",
    "transcript": "转写稿",
    "questions": "内部问题清单",
    "glossary": "修正词表",
    "other": "其他",
}


def _get_meeting(db: Session, meeting_id: int) -> Meeting:
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"meeting {meeting_id} not found")
    return m


def _get_file(db: Session, file_id: int) -> MeetingFile:
    f = db.get(MeetingFile, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"meeting file {file_id} not found")
    return f


def _get_file_version(db: Session, file: MeetingFile, version: str) -> MeetingFileVersion:
    v = (
        db.query(MeetingFileVersion)
        .filter(MeetingFileVersion.file_id == file.id, MeetingFileVersion.version == version)
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail=f"file {file.id} has no version {version}")
    return v


def _new_share_token() -> str:
    return f"mt-{secrets.token_hex(16)}"


def _new_series_token() -> str:
    return f"ms-{secrets.token_hex(16)}"


def _file_out(f: MeetingFile) -> dict:
    return {
        "id": f.id,
        "filename": f.filename,
        "kind": f.kind,
        "kind_label": KIND_LABELS.get(f.kind, f.kind),
        "current_version": f.current_version,
        "parse_status": f.parse_status,
        "parse_error": f.parse_error,
        "created_at": f.created_at,
    }


def _chunk_out(c: MeetingChunk) -> dict:
    return {
        "id": c.id,
        "seq": c.seq,
        "section": c.section,
        "ref_id": c.ref_id,
        "chunk_type": c.chunk_type,
        "fields": json.loads(c.fields_json or "{}"),
        "text_md": c.text_md,
    }


def _content_disposition(filename: str) -> str:
    """RFC 5987：中文文件名走 filename*=UTF-8''，ASCII 兜底给老客户端。"""
    fallback = filename.encode("ascii", "ignore").decode().replace('"', "") or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _version_out(v: MeetingFileVersion) -> dict:
    return {
        "version": v.version,
        "source": v.source,
        "bump": v.bump,
        "change_note": v.change_note,
        "created_by": v.created_by,
        "created_at": v.created_at,
    }


# ---------- 业务线 / 会议 ----------


@admin_router.get("/meeting-series")
def list_meeting_series(db: Session = Depends(get_db)):
    """业务线树：含各会议与文件数、汇总文档条目数摘要。"""
    return [
        {
            "id": s.id,
            "project_id": s.project_id,
            "name": s.name,
            "docs": [
                {"id": d.id, "kind": d.kind, "current_version": d.current_version,
                 "item_count": len(d.items)}
                for d in s.docs
            ],
            "meetings": [
                {
                    "id": m.id,
                    "name": m.name,
                    "date": m.date,
                    "dir_name": m.dir_name,
                    "file_count": len(m.files),
                }
                for m in s.meetings
            ],
        }
        for s in db.query(MeetingSeries).order_by(MeetingSeries.id).all()
    ]


@admin_router.post("/meeting-series", status_code=201)
def create_meeting_series(body: MeetingSeriesCreate, db: Session = Depends(get_db)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    s = MeetingSeries(project_id=body.project_id, name=body.name,
                      share_token=_new_series_token())
    db.add(s)
    db.commit()
    return {"id": s.id, "project_id": s.project_id, "name": s.name,
            "share_token": s.share_token}


@admin_router.post("/meetings", status_code=201)
def create_meeting(body: MeetingCreate, db: Session = Depends(get_db)):
    if db.get(MeetingSeries, body.series_id) is None:
        raise HTTPException(status_code=404, detail="meeting series not found")
    if body.date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.date):
            raise HTTPException(status_code=422, detail="date 必须是 YYYY-MM-DD 格式")
        date = body.date
    else:
        date = mp.parse_meeting_date(body.dir_name) or mp.parse_meeting_date(body.name)
    m = Meeting(
        series_id=body.series_id,
        name=body.name,
        date=date,
        dir_name=body.dir_name,
        share_token=_new_share_token(),
    )
    db.add(m)
    db.commit()
    return {
        "id": m.id,
        "series_id": m.series_id,
        "name": m.name,
        "date": m.date,
        "dir_name": m.dir_name,
        "share_token": m.share_token,
    }


@admin_router.get("/meetings/search")
def search_meeting_chunks(
    q: str = "",
    kind: str | None = None,
    status: str | None = None,
    series_id: int | None = None,
    db: Session = Depends(get_db),
):
    """切块搜索：LIKE 匹配 MeetingChunk.text_md，可按 chunk 类型 / 条目 status /
    业务线过滤，返回块 + 会议/文件定位信息。"""
    qy = (
        db.query(MeetingChunk, MeetingFile, Meeting)
        .join(MeetingFile, MeetingChunk.file_id == MeetingFile.id)
        .join(Meeting, MeetingFile.meeting_id == Meeting.id)
    )
    if q:
        qy = qy.filter(MeetingChunk.text_md.like(f"%{q}%"))
    if kind:
        qy = qy.filter(MeetingChunk.chunk_type == kind)
    if series_id is not None:
        qy = qy.filter(Meeting.series_id == series_id)
    results = []
    for chunk, file, meeting in qy.order_by(MeetingChunk.id).all():
        fields = json.loads(chunk.fields_json or "{}")
        if status and fields.get("status") != status:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "file_id": file.id,
                "filename": file.filename,
                "kind": file.kind,
                "meeting_id": meeting.id,
                "meeting_name": meeting.name,
                "series_id": meeting.series_id,
                "section": chunk.section,
                "ref_id": chunk.ref_id,
                "chunk_type": chunk.chunk_type,
                "fields": fields,
                "text_md": chunk.text_md,
            }
        )
        if len(results) >= 200:
            break
    return results


@admin_router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    m = _get_meeting(db, meeting_id)
    return {
        "id": m.id,
        "series_id": m.series_id,
        "series_name": m.series.name,
        "name": m.name,
        "date": m.date,
        "dir_name": m.dir_name,
        "share_token": m.share_token,
        "share_kinds": json.loads(m.share_kinds_json or "[]"),
        "files": [_file_out(f) for f in m.files],
        "created_at": m.created_at,
    }


@admin_router.patch("/meetings/{meeting_id}")
def update_meeting(
    meeting_id: int,
    body: MeetingUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """改会议元信息：name / date（YYYY-MM-DD，显式传 null 清空）/ dir_name。
    未传的字段保持不变（按 model_fields_set 区分「未传」与「传 null」）。"""
    m = _get_meeting(db, meeting_id)
    changes: dict = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name 不能为空")
        if name != m.name:
            changes["name"] = {"from": m.name, "to": name}
            m.name = name
    if "date" in body.model_fields_set:
        if body.date is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", body.date):
            raise HTTPException(status_code=422, detail="date 必须是 YYYY-MM-DD 格式或 null")
        if body.date != m.date:
            changes["date"] = {"from": m.date, "to": body.date}
            m.date = body.date
    if body.dir_name is not None and body.dir_name != m.dir_name:
        changes["dir_name"] = {"from": m.dir_name, "to": body.dir_name}
        m.dir_name = body.dir_name
    audit(db, key.hint, "meeting_update", f"meeting:{m.id}", changes)
    db.commit()
    return {
        "id": m.id,
        "series_id": m.series_id,
        "name": m.name,
        "date": m.date,
        "dir_name": m.dir_name,
    }


@admin_router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(
    meeting_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """删除会议：连带硬删全部文件及其版本与 chunks，不可恢复。"""
    m = _get_meeting(db, meeting_id)
    file_ids = [f.id for f in m.files]
    if file_ids:
        db.query(MeetingChunk).filter(MeetingChunk.file_id.in_(file_ids)).delete()
        db.query(MeetingFileVersion).filter(MeetingFileVersion.file_id.in_(file_ids)).delete()
        db.query(MeetingFile).filter(MeetingFile.id.in_(file_ids)).delete()
    audit(db, key.hint, "meeting_delete", f"meeting:{m.id}",
          {"name": m.name, "deleted_files": len(file_ids)})
    db.delete(m)
    db.commit()
    return Response(status_code=204)


@admin_router.delete("/meeting-series/{series_id}", status_code=204)
def delete_meeting_series(
    series_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """删除业务线：连带硬删其下全部会议（含文件/版本/chunks），不可恢复。"""
    s = db.get(MeetingSeries, series_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"meeting series {series_id} not found")
    deleted_meetings = 0
    for m in list(s.meetings):
        file_ids = [f.id for f in m.files]
        if file_ids:
            db.query(MeetingChunk).filter(MeetingChunk.file_id.in_(file_ids)).delete()
            db.query(MeetingFileVersion).filter(MeetingFileVersion.file_id.in_(file_ids)).delete()
            db.query(MeetingFile).filter(MeetingFile.id.in_(file_ids)).delete()
        db.delete(m)
        deleted_meetings += 1
    for d in list(s.docs):  # 汇总文档一并级联
        db.query(SeriesItem).filter(SeriesItem.doc_id == d.id).delete()
        db.query(SeriesDocVersion).filter(SeriesDocVersion.doc_id == d.id).delete()
        db.delete(d)
    audit(db, key.hint, "meeting_series_delete", f"meeting_series:{s.id}",
          {"name": s.name, "deleted_meetings": deleted_meetings})
    db.delete(s)
    db.commit()
    return Response(status_code=204)


def _fix_filename(name: str) -> str:
    """multipart 文件名乱码恢复：非浏览器客户端（如中文 Windows 的 curl）
    可能按 GBK 编码文件名，被 Starlette 按 latin-1 解码成乱码。依次尝试
    utf-8 / gbk 还原；都失败则原样返回（浏览器场景本就正确）。"""
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


@admin_router.post("/meetings/{meeting_id}/upload")
async def upload_meeting_files(
    meeting_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """multipart 批量上传：逐文件 detect_kind →（精准需求/业务事实则 parse）
    → 存文件 + v1 版本 + chunks。解析失败不影响同批其他文件（逐文件返回
    status/error）；同会议同文件名重复上传拒绝（整批都是重复时 409）；
    同名且上次 parse_status=failed 的文件允许重传（覆盖失败记录）。"""
    meeting = _get_meeting(db, meeting_id)
    decoded: list[tuple[str, str]] = []
    for f in files:
        raw = await f.read()
        try:
            decoded.append((_fix_filename(f.filename or "unnamed.md"), raw.decode("utf-8-sig")))
        except UnicodeDecodeError:
            decoded.append((_fix_filename(f.filename or "unnamed.md"), ""))  # 标记位，下面统一报错

    existing = {f.filename: f for f in meeting.files}
    duplicates = [
        name
        for name, _ in decoded
        if name in existing and existing[name].parse_status != "failed"
    ]
    if duplicates and len(duplicates) == len(decoded):
        raise HTTPException(
            status_code=409,
            detail=f"会议内已存在同名文件，重复上传已拒绝：{'、'.join(duplicates)}",
        )

    results = []
    for filename, text in decoded:
        if filename in duplicates:
            results.append({"filename": filename, "status": "duplicate",
                            "error": "会议内已存在同名文件"})
            continue
        stale = existing.get(filename)
        if stale is not None:  # 上次解析失败的同名文件：允许重传覆盖
            db.query(MeetingChunk).filter(MeetingChunk.file_id == stale.id).delete()
            db.query(MeetingFileVersion).filter(MeetingFileVersion.file_id == stale.id).delete()
            db.delete(stale)
            db.flush()

        kind = mp.detect_kind(filename)
        chunks: list[dict] = []
        parse_status, parse_error = "na", ""
        if not text:
            parse_status, parse_error = "failed", "文件不是有效的 UTF-8 文本"
        elif kind in mp.CHUNKED_KINDS:
            try:
                chunks = mp.parse_items(text, kind)
                parse_status = "ok"
            except mp.MeetingParseError as exc:
                parse_status = "failed"
                parse_error = (
                    f"文件「{filename}」第 {exc.line} 行格式错误："
                    f"期望 {exc.expected}；实际内容：{exc.actual}"
                )

        file = MeetingFile(
            meeting_id=meeting.id,
            filename=filename,
            kind=kind,
            current_version="1.0.0",
            content_md=text,
            parse_status=parse_status,
            parse_error=parse_error,
        )
        db.add(file)
        db.flush()
        db.add(
            MeetingFileVersion(
                file_id=file.id, version="1.0.0", content_md=text,
                source="upload", bump="none", created_by=key.hint,
            )
        )
        for seq, c in enumerate(chunks):
            db.add(
                MeetingChunk(
                    file_id=file.id,
                    seq=seq,
                    section=c["section"],
                    ref_id=c["ref_id"],
                    chunk_type=c["chunk_type"],
                    fields_json=json.dumps(c["fields"], ensure_ascii=False),
                    text_md=c["text_md"],
                )
            )
        results.append(
            {
                "filename": filename,
                "kind": kind,
                "file_id": file.id,
                "status": "ok" if parse_status in ("ok", "na") else "failed",
                "parse_status": parse_status,
                "chunk_count": len(chunks),
                "error": parse_error or None,
            }
        )

    audit(
        db, key.hint, "meeting_upload", f"meeting:{meeting.id}",
        {"files": [{"filename": r["filename"], "status": r["status"]} for r in results]},
    )
    db.commit()
    return {"meeting_id": meeting.id, "results": results}


@admin_router.post("/meetings/{meeting_id}/share-token/regenerate")
def regenerate_share_token(
    meeting_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """重新生成哈希码：旧码立即失效。"""
    m = _get_meeting(db, meeting_id)
    old = m.share_token
    m.share_token = _new_share_token()
    audit(db, key.hint, "meeting_token_regenerate", f"meeting:{m.id}", {})
    db.commit()
    return {"id": m.id, "share_token": m.share_token, "old_token_hint": f"mt-…{old[-4:]}"}


@admin_router.put("/meetings/{meeting_id}/share-kinds")
def update_share_kinds(meeting_id: int, body: ShareKindsUpdate, db: Session = Depends(get_db)):
    m = _get_meeting(db, meeting_id)
    unknown = [k for k in body.kinds if k not in mp.ALL_KINDS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"未知分享范围：{'、'.join(unknown)}；可选：{'、'.join(mp.ALL_KINDS)}",
        )
    m.share_kinds_json = json.dumps(body.kinds, ensure_ascii=False)
    db.commit()
    return {"id": m.id, "share_kinds": body.kinds}


@admin_router.get("/meetings/{meeting_id}/export")
def export_meeting(
    meeting_id: int, with_diffs: int = 0, db: Session = Depends(get_db)
):
    """整会议 zip：所有文件当前版；with_diffs=1 时附带相邻版本 diff 日志。"""
    m = _get_meeting(db, meeting_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in m.files:
            z.writestr(f.filename, f.content_md)
            if with_diffs:
                versions = f.versions
                for a, b in zip(versions, versions[1:]):
                    diff = "\n".join(
                        difflib.unified_diff(
                            a.content_md.splitlines(), b.content_md.splitlines(),
                            fromfile=f"{f.filename}@{a.version}",
                            tofile=f"{f.filename}@{b.version}", lineterm="",
                        )
                    )
                    z.writestr(f"diffs/{f.filename}.{a.version}-{b.version}.diff.md", diff)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(f"{m.name}.zip")},
    )


# ---------- 业务线汇总文档（总精准需求 / 总业务事实） ----------

SERIES_DOC_TITLES = {"requirements": "总精准需求", "facts": "总业务事实"}


def _get_series(db: Session, series_id: int) -> MeetingSeries:
    s = db.get(MeetingSeries, series_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"meeting series {series_id} not found")
    return s


def _get_series_doc(db: Session, doc_id: int) -> SeriesDoc:
    d = db.get(SeriesDoc, doc_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"series doc {doc_id} not found")
    return d


def _series_doc_out(d: SeriesDoc) -> dict:
    return {
        "id": d.id,
        "series_id": d.series_id,
        "kind": d.kind,
        "kind_label": SERIES_DOC_TITLES.get(d.kind, d.kind),
        "current_version": d.current_version,
        "item_count": len(d.items),
    }


def _series_item_dict(i: SeriesItem) -> dict:
    return {
        "ref_id": i.ref_id,
        "chunk_type": i.chunk_type,
        "section": i.section,
        "fields": json.loads(i.fields_json or "{}"),
    }


def _series_item_out(i: SeriesItem) -> dict:
    origin_label = (
        f"{i.origin_meeting_name} · {i.origin_ref_id}" if i.origin_ref_id else "业务级增加"
    )
    return {
        **_series_item_dict(i),
        "id": i.id,
        "seq": i.seq,
        "text_md": i.text_md,
        "origin_chunk_id": i.origin_chunk_id,
        "origin_meeting_id": i.origin_meeting_id,
        "origin_ref_id": i.origin_ref_id,
        "origin_meeting_name": i.origin_meeting_name,
        "origin_label": origin_label,
    }


def _series_doc_pool(doc: SeriesDoc) -> set[str]:
    """编号历史池：当前条目 + 全部版本快照里的 ref_id（新编号不复用已删编号）。"""
    pool = {i.ref_id for i in doc.items if i.ref_id}
    for v in doc.versions:
        pool.update(re.findall(r"^- id:\s*(\S+)", v.content_md, flags=re.M))
    return pool


def _render_series_doc(doc: SeriesDoc, with_origin: bool) -> str:
    """渲染汇总文档为 minutes2reqs 格式。with_origin=True（导出/分享）时每个
    条目在字段区末尾加 `  来源: 会议名 · 原编号`（业务级增加 → 该文案）——
    来源行只是渲染产物，不进 fields_json。"""
    series = doc.series
    parts = [f"# {series.name} · {SERIES_DOC_TITLES.get(doc.kind, doc.kind)}"]
    for i in doc.items:
        fields = json.loads(i.fields_json or "{}")
        if i.chunk_type == "prose":
            parts.append(fields.get("raw", ""))
            continue
        if with_origin:
            label = (
                f"{i.origin_meeting_name} · {i.origin_ref_id}"
                if i.origin_ref_id
                else "业务级增加"
            )
            fields = {**fields, "来源": label}
        parts.append(mp.render_item(i.ref_id, fields))
    return "\n\n".join(p for p in parts if p) + "\n"


@admin_router.get("/meeting-series/{series_id}")
def get_meeting_series_detail(series_id: int, db: Session = Depends(get_db)):
    """业务线详情：信息 + 哈希码 + 会议列表 + 汇总文档摘要。"""
    s = _get_series(db, series_id)
    return {
        "id": s.id,
        "project_id": s.project_id,
        "name": s.name,
        "share_token": s.share_token,
        "created_at": s.created_at,
        "meetings": [
            {"id": m.id, "name": m.name, "date": m.date, "dir_name": m.dir_name,
             "file_count": len(m.files)}
            for m in s.meetings
        ],
        "docs": [_series_doc_out(d) for d in s.docs],
    }


@admin_router.post("/meeting-series/{series_id}/refresh-docs")
def refresh_series_docs(
    series_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """从各会议文件刷新汇总文档（幂等合并）：已汇总条目（按 origin_chunk_id
    匹配，源文件被重写后按 会议+原编号 兜底跟随新 id）保留人工编辑不动；
    新出现的源块追加新条目并顺序编号。首次创建文档（1.0.0 / refresh）；
    后续有新增 → minor 新版本，无新增不动。"""
    s = _get_series(db, series_id)
    results = []
    for kind in ("requirements", "facts"):
        src_chunks = (
            db.query(MeetingChunk)
            .join(MeetingFile, MeetingChunk.file_id == MeetingFile.id)
            .join(Meeting, MeetingFile.meeting_id == Meeting.id)
            .filter(
                Meeting.series_id == s.id,
                MeetingFile.kind == kind,
                MeetingFile.parse_status == "ok",
                MeetingChunk.chunk_type != "prose",
            )
            .order_by(Meeting.id, MeetingFile.id, MeetingChunk.seq)
            .all()
        )
        doc = next((d for d in s.docs if d.kind == kind), None)
        first_time = doc is None
        if first_time:
            doc = SeriesDoc(series_id=s.id, kind=kind)
            db.add(doc)
            db.flush()
        existing_by_chunk = {i.origin_chunk_id: i for i in doc.items if i.origin_chunk_id}
        existing_by_ref = {
            (i.origin_meeting_id, i.origin_ref_id): i for i in doc.items if i.origin_ref_id
        }
        pool = _series_doc_pool(doc)
        seq = max((i.seq for i in doc.items), default=-1) + 1
        added = 0
        for c in src_chunks:
            meeting_id = c.file.meeting_id
            hit = existing_by_chunk.get(c.id) or existing_by_ref.get((meeting_id, c.ref_id))
            if hit is not None:
                if hit.origin_chunk_id != c.id:
                    hit.origin_chunk_id = c.id  # 源文件重写导致 chunk id 变化，跟随
                continue
            prefix = mp.CHUNK_TYPE_PREFIX[c.chunk_type]
            ref_id = mp.next_ref_id(sorted(pool), prefix)
            pool.add(ref_id)
            fields = json.loads(c.fields_json or "{}")
            db.add(
                SeriesItem(
                    doc_id=doc.id, seq=seq, chunk_type=c.chunk_type, section=c.section,
                    ref_id=ref_id, fields_json=json.dumps(fields, ensure_ascii=False),
                    text_md=mp.render_item(ref_id, fields),
                    origin_chunk_id=c.id, origin_meeting_id=meeting_id,
                    origin_ref_id=c.ref_id, origin_meeting_name=c.file.meeting.name,
                )
            )
            seq += 1
            added += 1
        if first_time:
            db.add(
                SeriesDocVersion(
                    doc_id=doc.id, version="1.0.0",
                    content_md=_render_series_doc(doc, with_origin=False),
                    source="refresh", bump="none",
                    change_note=f"首次汇总，{added} 条", created_by=key.hint,
                )
            )
        elif added:
            version = mp.bump_version(doc.current_version, "minor")
            doc.current_version = version
            db.add(
                SeriesDocVersion(
                    doc_id=doc.id, version=version,
                    content_md=_render_series_doc(doc, with_origin=False),
                    source="refresh", bump="minor",
                    change_note=f"从会议刷新，新增 {added} 条", created_by=key.hint,
                )
            )
        results.append({"kind": kind, "doc_id": doc.id, "added": added,
                        "version": doc.current_version})
    audit(db, key.hint, "series_docs_refresh", f"meeting_series:{s.id}",
          {"docs": [{"kind": r["kind"], "added": r["added"]} for r in results]})
    db.commit()
    return {"series_id": s.id, "docs": results}


def _link_update_source(
    db: Session, item: SeriesItem, fields: dict, actor: str
) -> tuple[str | None, str | None, int | None]:
    """联动改：把汇总条目的标量字段变更应用到源块，源文件走完整保存管线
    （自动 bump + 新版本 + 重写 chunks）。返回 (源文件名, 源文件新版本, 新源块 id)；
    源块/源文件不存在 → (None, None, None)。quotes 不联动。"""
    src = db.get(MeetingChunk, item.origin_chunk_id) if item.origin_chunk_id else None
    if src is None:
        return None, None, None
    f = db.get(MeetingFile, src.file_id)
    if f is None:
        return None, None, None
    chunks = _file_chunk_dicts(f)
    for c in chunks:
        if c["ref_id"] == src.ref_id:
            scalars = {k: v for k, v in fields.items() if k != "quotes"}
            c["fields"] = {**scalars, "quotes": c["fields"].get("quotes", [])}
            break
    version, _ = _save_file_chunks(
        db, f, chunks, actor, f"汇总文档联动更新 {item.ref_id}"
    )
    db.flush()
    new_chunk = (
        db.query(MeetingChunk)
        .filter(MeetingChunk.file_id == f.id, MeetingChunk.ref_id == src.ref_id)
        .first()
    )
    return f.filename, version, new_chunk.id if new_chunk else None


def _link_delete_source(
    db: Session, item: SeriesItem, actor: str
) -> tuple[str | None, str | None]:
    """联动删：源文件删掉对应块（major bump）。源已不存在 → (None, None)。"""
    src = db.get(MeetingChunk, item.origin_chunk_id) if item.origin_chunk_id else None
    if src is None:
        return None, None
    f = db.get(MeetingFile, src.file_id)
    if f is None:
        return None, None
    chunks = [c for c in _file_chunk_dicts(f) if c["ref_id"] != src.ref_id]
    version, _ = _save_file_chunks(
        db, f, chunks, actor, f"汇总文档联动删除 {item.ref_id}"
    )
    return f.filename, version


@admin_router.put("/series-docs/{doc_id}/items")
def update_series_items(
    doc_id: int,
    body: SeriesItemsUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """汇总文档块级保存（全量提交，与 PUT /files/{id}/chunks 同模式）：
    改/删有来源的条目联动源会议文件（完整保存管线）；新增条目 origin 为空
    =「业务级增加」；汇总文档自身按 compute_bump 产生新版本。"""
    doc = _get_series_doc(db, doc_id)
    allowed = (
        {"req", "con", "act", "q", "prose"}
        if doc.kind == "requirements"
        else {"fact", "prose"}
    )
    old_items = list(doc.items)
    old_by_ref = {i.ref_id: i for i in old_items if i.ref_id}
    old_dicts = [_series_item_dict(i) for i in old_items]
    pool = _series_doc_pool(doc)

    # (ref_id, chunk_type, section, fields, origin 四元组)
    new_rows: list[dict] = []
    links: list[dict] = []
    assigned: dict[str, int] = {}
    for idx, c in enumerate(body.items):
        if c.chunk_type not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"第 {idx + 1} 个块 chunk_type={c.chunk_type!r} 不属于该汇总文档",
            )
        fields = dict(c.fields)
        if c.chunk_type == "prose":
            if not isinstance(fields.get("raw"), str):
                raise HTTPException(status_code=422, detail=f"第 {idx + 1} 个 prose 块缺少 fields.raw")
            new_rows.append({"ref_id": None, "chunk_type": "prose", "section": c.section,
                             "fields": {"raw": fields["raw"]},
                             "origin": (None, None, None, "")})
            continue
        prefix = mp.CHUNK_TYPE_PREFIX[c.chunk_type]
        ref_id = c.ref_id
        old = None
        if ref_id:
            if not re.match(rf"^{prefix}-\d+$", ref_id):
                raise HTTPException(
                    status_code=422,
                    detail=f"第 {idx + 1} 个块 ref_id={ref_id!r} 与前缀 {prefix}- 不匹配",
                )
            assigned[ref_id] = assigned.get(ref_id, 0) + 1
            if assigned[ref_id] > 1:
                raise HTTPException(status_code=422, detail=f"ref_id {ref_id} 重复出现")
            old = old_by_ref.get(ref_id)
        else:
            ref_id = mp.next_ref_id(sorted(pool), prefix)
            pool.add(ref_id)
        required = "question" if c.chunk_type == "q" else "statement"
        if not str(fields.get(required) or "").strip():
            raise HTTPException(
                status_code=422, detail=f"第 {idx + 1} 个块（{ref_id}）缺少 {required} 字段"
            )
        if "quotes" not in fields:  # quotes 只读，缺省时从旧条目继承
            old_fields = json.loads(old.fields_json or "{}") if old else {}
            fields["quotes"] = list(old_fields.get("quotes", []))
        if old is not None:
            origin = (old.origin_chunk_id, old.origin_meeting_id,
                      old.origin_ref_id, old.origin_meeting_name)
        else:  # 业务级增加
            origin = (None, None, None, "")
            links.append({"ref_id": ref_id, "action": "added", "origin": "业务级增加",
                          "source_file": None, "source_version": None})
        new_rows.append({"ref_id": ref_id, "chunk_type": c.chunk_type, "section": c.section,
                         "fields": fields, "origin": origin})

    # 联动改：字段有 diff 且有来源
    for row in new_rows:
        if row["chunk_type"] == "prose":
            continue
        old = old_by_ref.get(row["ref_id"])
        if old is None or not old.origin_chunk_id:
            continue
        old_fields = json.loads(old.fields_json or "{}")
        if row["fields"] == old_fields:
            continue
        fname, fver, new_chunk_id = _link_update_source(db, old, row["fields"], key.hint)
        if new_chunk_id is not None:
            row["origin"] = (new_chunk_id, row["origin"][1], row["origin"][2], row["origin"][3])
        links.append({
            "ref_id": row["ref_id"], "action": "updated",
            "origin": f"{old.origin_meeting_name} · {old.origin_ref_id}",
            "source_file": fname or "源已不存在", "source_version": fver,
        })

    # 联动删：旧条目不在新提交里
    new_refs = {r["ref_id"] for r in new_rows if r["ref_id"]}
    for old in old_items:
        if not old.ref_id or old.ref_id in new_refs:
            continue
        entry = {"ref_id": old.ref_id, "action": "deleted",
                 "origin": f"{old.origin_meeting_name} · {old.origin_ref_id}"
                 if old.origin_ref_id else "业务级增加",
                 "source_file": None, "source_version": None}
        if old.origin_chunk_id:
            fname, fver = _link_delete_source(db, old, key.hint)
            entry["source_file"] = fname or "源已不存在"
            entry["source_version"] = fver
        links.append(entry)

    new_dicts = [{k: r[k] for k in ("ref_id", "chunk_type", "section", "fields")}
                 for r in new_rows]
    bump = mp.compute_bump(old_dicts, new_dicts)
    version = mp.bump_version(doc.current_version, bump)
    content = mp.render_file(new_dicts)

    db.query(SeriesItem).filter(SeriesItem.doc_id == doc.id).delete()
    for seq, r in enumerate(new_rows):
        o_chunk, o_meeting, o_ref, o_name = r["origin"]
        db.add(
            SeriesItem(
                doc_id=doc.id, seq=seq, chunk_type=r["chunk_type"], section=r["section"],
                ref_id=r["ref_id"],
                fields_json=json.dumps(r["fields"], ensure_ascii=False),
                text_md=r["fields"]["raw"] if r["chunk_type"] == "prose"
                else mp.render_item(r["ref_id"], r["fields"]),
                origin_chunk_id=o_chunk, origin_meeting_id=o_meeting,
                origin_ref_id=o_ref, origin_meeting_name=o_name,
            )
        )
    doc.current_version = version
    db.add(
        SeriesDocVersion(
            doc_id=doc.id, version=version, content_md=content, source="edit",
            bump=bump, change_note=body.change_note, created_by=key.hint,
        )
    )
    audit(db, key.hint, "series_items_edit", f"series_doc:{doc.id}@{version}",
          {"bump": bump, "change_note": body.change_note,
           "links": [{"ref_id": l["ref_id"], "action": l["action"]} for l in links]})
    db.commit()
    return {"doc_id": doc.id, "version": version, "bump": bump, "links": links}


@admin_router.get("/series-docs/{doc_id}")
def get_series_doc(doc_id: int, db: Session = Depends(get_db)):
    doc = _get_series_doc(db, doc_id)
    return {
        **_series_doc_out(doc),
        "series_name": doc.series.name,
        "items": [_series_item_out(i) for i in doc.items],
        "versions": [
            {"version": v.version, "source": v.source, "bump": v.bump,
             "change_note": v.change_note, "created_by": v.created_by,
             "created_at": v.created_at}
            for v in doc.versions
        ],
    }


@admin_router.get("/series-docs/{doc_id}/diff")
def diff_series_doc(
    doc_id: int,
    from_: str = Query(alias="from"),
    to: str = Query(),
    db: Session = Depends(get_db),
):
    doc = _get_series_doc(db, doc_id)
    versions = {v.version: v for v in doc.versions}
    a, b = versions.get(from_), versions.get(to)
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="version not found")
    title = SERIES_DOC_TITLES.get(doc.kind, doc.kind)
    diff = "\n".join(
        difflib.unified_diff(
            a.content_md.splitlines(), b.content_md.splitlines(),
            fromfile=f"{title}@{from_}", tofile=f"{title}@{to}", lineterm="",
        )
    )
    return {"doc_id": doc.id, "from": from_, "to": to, "diff": diff}


@admin_router.get("/series-docs/{doc_id}/export")
def export_series_doc(doc_id: int, db: Session = Depends(get_db)):
    """导出汇总文档（带来源行），文件名 {业务线名}_总精准需求.md / _总业务事实.md。"""
    doc = _get_series_doc(db, doc_id)
    content = _render_series_doc(doc, with_origin=True)
    filename = f"{doc.series.name}_{SERIES_DOC_TITLES.get(doc.kind, doc.kind)}.md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@admin_router.post("/meeting-series/{series_id}/share-token/regenerate")
def regenerate_series_token(
    series_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """重新生成业务线哈希码：旧码立即失效。"""
    s = _get_series(db, series_id)
    old = s.share_token
    s.share_token = _new_series_token()
    audit(db, key.hint, "series_token_regenerate", f"meeting_series:{s.id}", {})
    db.commit()
    return {"id": s.id, "share_token": s.share_token,
            "old_token_hint": f"ms-…{old[-4:]}" if old else None}


# ---------- 文件 ----------


@admin_router.get("/files/{file_id}")
def get_meeting_file(file_id: int, db: Session = Depends(get_db)):
    f = _get_file(db, file_id)
    return {
        **_file_out(f),
        "meeting_id": f.meeting_id,
        "content_md": f.content_md,
        "chunks": [_chunk_out(c) for c in f.chunks],
        "versions": [_version_out(v) for v in f.versions],
    }


def _reparse_chunks(db: Session, f: MeetingFile) -> int:
    """按当前 kind 对 content_md 重新解析重建 chunks，返回块数。

    chunks 是 content 的派生物，重解析不产生新版本。非切块类清空 chunks
    并置 parse_status=na。"""
    db.query(MeetingChunk).filter(MeetingChunk.file_id == f.id).delete()
    if f.kind not in mp.CHUNKED_KINDS:
        f.parse_status = "na"
        f.parse_error = ""
        return 0
    try:
        chunks = mp.parse_items(f.content_md, f.kind)
    except mp.MeetingParseError as exc:
        f.parse_status = "failed"
        f.parse_error = (
            f"文件「{f.filename}」第 {exc.line} 行格式错误："
            f"期望 {exc.expected}；实际内容：{exc.actual}"
        )
        return 0
    for seq, c in enumerate(chunks):
        db.add(
            MeetingChunk(
                file_id=f.id,
                seq=seq,
                section=c["section"],
                ref_id=c["ref_id"],
                chunk_type=c["chunk_type"],
                fields_json=json.dumps(c["fields"], ensure_ascii=False),
                text_md=c["text_md"],
            )
        )
    f.parse_status = "ok"
    f.parse_error = ""
    return len(chunks)


@admin_router.post("/files/{file_id}/reparse")
def reparse_file(
    file_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """重新按当前文件名 detect_kind 并重解析重建 chunks（不产生新版本）。
    用途：识别规则修复后挽救存量数据；修好源文件格式后也可走重传。"""
    f = _get_file(db, file_id)
    f.kind = mp.detect_kind(f.filename)
    chunk_count = _reparse_chunks(db, f)
    audit(
        db, key.hint, "meeting_reparse", f"meeting_file:{f.id}",
        {"kind": f.kind, "parse_status": f.parse_status, "chunk_count": chunk_count},
    )
    db.commit()
    return {**_file_out(f), "chunk_count": chunk_count}


@admin_router.delete("/files/{file_id}", status_code=204)
def delete_file(
    file_id: int, db: Session = Depends(get_db), key: ApiKey = Depends(require_human)
):
    """删除文件及其全部版本与 chunks（硬删，不可恢复）。"""
    f = _get_file(db, file_id)
    db.query(MeetingChunk).filter(MeetingChunk.file_id == f.id).delete()
    db.query(MeetingFileVersion).filter(MeetingFileVersion.file_id == f.id).delete()
    audit(db, key.hint, "meeting_file_delete", f"meeting_file:{f.id}",
          {"filename": f.filename, "meeting_id": f.meeting_id})
    db.delete(f)
    db.commit()
    return Response(status_code=204)


@admin_router.patch("/files/{file_id}")
def rename_file(
    file_id: int,
    body: FileRename,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """重命名文件：同会议内文件名冲突 409；改名后重新 detect_kind，
    kind 变化时自动重解析（切块类重建 chunks，非切块类清空）。"""
    f = _get_file(db, file_id)
    new_name = body.filename.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="filename 不能为空")
    if new_name == f.filename:
        return _file_out(f)
    conflict = (
        db.query(MeetingFile)
        .filter(
            MeetingFile.meeting_id == f.meeting_id,
            MeetingFile.filename == new_name,
            MeetingFile.id != f.id,
        )
        .first()
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail=f"会议内已存在同名文件：{new_name}")
    old_name, old_kind = f.filename, f.kind
    f.filename = new_name
    f.kind = mp.detect_kind(new_name)
    chunk_count = None
    if f.kind != old_kind:
        chunk_count = _reparse_chunks(db, f)
    audit(
        db, key.hint, "meeting_file_rename", f"meeting_file:{f.id}",
        {"from": old_name, "to": new_name, "kind": f.kind},
    )
    db.commit()
    return {**_file_out(f), "chunk_count": chunk_count}


def _file_chunk_dicts(f: MeetingFile) -> list[dict]:
    """文件当前 chunks → dict 列表（bump 比较 / 渲染 / 联动编辑共用）。"""
    return [
        {
            "ref_id": c.ref_id,
            "chunk_type": c.chunk_type,
            "section": c.section,
            "fields": json.loads(c.fields_json or "{}"),
        }
        for c in f.chunks
    ]


def _save_file_chunks(
    db: Session, f: MeetingFile, new_chunks: list[dict], actor: str, change_note: str
) -> tuple[str, str]:
    """切块文件保存管线（PUT /files/{id}/chunks 与汇总文档联动共用）：
    compute_bump → 渲染 → 新版本 + 重写 chunks + 审计。new_chunks 须已校验。"""
    old_chunks = _file_chunk_dicts(f)
    bump = mp.compute_bump(old_chunks, new_chunks)
    version = mp.bump_version(f.current_version, bump)
    content = mp.render_file(new_chunks)

    db.query(MeetingChunk).filter(MeetingChunk.file_id == f.id).delete()
    for seq, c in enumerate(new_chunks):
        db.add(
            MeetingChunk(
                file_id=f.id, seq=seq, section=c["section"], ref_id=c["ref_id"],
                chunk_type=c["chunk_type"],
                fields_json=json.dumps(c["fields"], ensure_ascii=False),
                text_md=c["fields"]["raw"] if c["chunk_type"] == "prose"
                else mp.render_item(c["ref_id"], c["fields"]),
            )
        )
    f.content_md = content
    f.current_version = version
    db.add(
        MeetingFileVersion(
            file_id=f.id, version=version, content_md=content, source="edit",
            bump=bump, change_note=change_note, created_by=actor,
        )
    )
    audit(db, actor, "meeting_chunk_edit", f"meeting_file:{f.id}@{version}",
          {"bump": bump, "change_note": change_note})
    return version, bump


@admin_router.put("/files/{file_id}/chunks")
def update_file_chunks(
    file_id: int,
    body: ChunkUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """切块文件保存：全量提交 chunks（改字段/增/删/排序）→ compute_bump
    自动算版本 → 渲染 → 新版本 + 重写 chunks。quotes 只读：提交里缺省时
    从旧块按 ref_id 继承。"""
    f = _get_file(db, file_id)
    if f.kind not in mp.CHUNKED_KINDS:
        raise HTTPException(status_code=409, detail=f"{f.kind} 文件不是切块文件，请用 PUT /content")
    allowed_types = {"req", "con", "act", "q", "prose"} if f.kind == "requirements" else {"fact", "prose"}

    old_chunks = _file_chunk_dicts(f)
    # 历史 ref_id（含已删条目，扫全部版本快照）：新条目编号不复用已删编号
    historical_ids: set[str] = set()
    for v in f.versions:
        historical_ids.update(re.findall(r"^- id:\s*(\S+)", v.content_md, flags=re.M))

    new_chunks: list[dict] = []
    assigned: dict[str, int] = {}  # ref_id -> 出现次数（重复检测）
    for i, c in enumerate(body.chunks):
        if c.chunk_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail=f"第 {i + 1} 个块 chunk_type={c.chunk_type!r} 不属于 {f.kind} 文件",
            )
        fields = dict(c.fields)
        if c.chunk_type == "prose":
            if not isinstance(fields.get("raw"), str):
                raise HTTPException(status_code=422, detail=f"第 {i + 1} 个 prose 块缺少 fields.raw")
            new_chunks.append({"ref_id": None, "chunk_type": "prose",
                               "section": c.section, "fields": {"raw": fields["raw"]}})
            continue
        prefix = mp.CHUNK_TYPE_PREFIX[c.chunk_type]
        ref_id = c.ref_id
        if ref_id:
            if not re.match(rf"^{prefix}-\d+$", ref_id):
                raise HTTPException(
                    status_code=422,
                    detail=f"第 {i + 1} 个块 ref_id={ref_id!r} 与类型 {c.chunk_type}（前缀 {prefix}-）不匹配",
                )
            assigned[ref_id] = assigned.get(ref_id, 0) + 1
            if assigned[ref_id] > 1:
                raise HTTPException(status_code=422, detail=f"ref_id {ref_id} 重复出现")
        else:
            pool = historical_ids | {c2["ref_id"] for c2 in new_chunks if c2["ref_id"]}
            ref_id = mp.next_ref_id(sorted(pool), prefix)
            historical_ids.add(ref_id)
        required = "question" if c.chunk_type == "q" else "statement"
        if not str(fields.get(required) or "").strip():
            raise HTTPException(status_code=422, detail=f"第 {i + 1} 个块（{ref_id}）缺少 {required} 字段")
        if "quotes" not in fields:  # quotes 只读，未提交时从旧块继承
            old = next((o for o in old_chunks if o["ref_id"] == ref_id), None)
            fields["quotes"] = list(old["fields"].get("quotes", [])) if old else []
        new_chunks.append({"ref_id": ref_id, "chunk_type": c.chunk_type,
                           "section": c.section, "fields": fields})

    version, bump = _save_file_chunks(db, f, new_chunks, key.hint, body.change_note)
    db.commit()
    return {"file_id": f.id, "version": version, "bump": bump}


@admin_router.put("/files/{file_id}/content")
def update_file_content(
    file_id: int,
    body: ContentUpdate,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_human),
):
    """非切块文件整篇保存：用户手选 bump（默认 patch）。"""
    f = _get_file(db, file_id)
    if f.kind in mp.CHUNKED_KINDS:
        raise HTTPException(status_code=409, detail="切块文件请用 PUT /chunks 编辑")
    version = mp.bump_version(f.current_version, body.bump)
    f.content_md = body.content
    f.current_version = version
    db.add(
        MeetingFileVersion(
            file_id=f.id, version=version, content_md=body.content, source="edit",
            bump=body.bump, change_note=body.change_note, created_by=key.hint,
        )
    )
    audit(db, key.hint, "meeting_content_edit", f"meeting_file:{f.id}@{version}",
          {"bump": body.bump, "change_note": body.change_note})
    db.commit()
    return {"file_id": f.id, "version": version, "bump": body.bump}


@admin_router.get("/files/{file_id}/versions/{version}")
def get_file_version(file_id: int, version: str, db: Session = Depends(get_db)):
    f = _get_file(db, file_id)
    v = _get_file_version(db, f, version)
    return {**_version_out(v), "file_id": f.id, "filename": f.filename, "content_md": v.content_md}


@admin_router.get("/files/{file_id}/diff")
def diff_file_versions(
    file_id: int,
    from_: str = Query(alias="from"),
    to: str = Query(),
    download: int = 0,
    db: Session = Depends(get_db),
):
    """两版本 unified diff；?download=1 导出 .md 附件。"""
    f = _get_file(db, file_id)
    a = _get_file_version(db, f, from_)
    b = _get_file_version(db, f, to)
    diff = "\n".join(
        difflib.unified_diff(
            a.content_md.splitlines(), b.content_md.splitlines(),
            fromfile=f"{f.filename}@{from_}", tofile=f"{f.filename}@{to}", lineterm="",
        )
    )
    if download:
        stem = f.filename.rsplit(".md", 1)[0]
        return Response(
            content=diff,
            media_type="text/markdown",
            headers={"Content-Disposition": _content_disposition(f"{stem}.{from_}-{to}.diff.md")},
        )
    return {"file_id": f.id, "from": from_, "to": to, "diff": diff}


@admin_router.get("/files/{file_id}/export")
def export_file(file_id: int, version: str | None = None, db: Session = Depends(get_db)):
    """按原文件名导出当前/指定版本。"""
    f = _get_file(db, file_id)
    content = f.content_md if version is None else _get_file_version(db, f, version).content_md
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": _content_disposition(f.filename)},
    )


# ---------- 哈希码分享（无 API key，token 即授权） ----------


def _meeting_by_token(db: Session, token: str) -> Meeting:
    m = db.query(Meeting).filter(Meeting.share_token == token).first()
    if m is None:
        raise HTTPException(status_code=404, detail="share token not found")
    return m


def _render_share_markdown(meeting: Meeting, kinds: list[str]) -> str:
    parts = [f"# 会议记录：{meeting.name}", ""]
    parts.append(f"- 业务线：{meeting.series.name}")
    parts.append(f"- 日期：{meeting.date or '未设置'}")
    if meeting.dir_name:
        parts.append(f"- 原始目录：{meeting.dir_name}")
    by_kind: dict[str, list[MeetingFile]] = {}
    for f in meeting.files:
        if f.kind in kinds:
            by_kind.setdefault(f.kind, []).append(f)
    for kind in mp.ALL_KINDS:
        files = by_kind.get(kind)
        if not files:
            continue
        parts.append("")
        parts.append(f"## {KIND_LABELS[kind]}")
        for f in files:
            parts.append("")
            parts.append(f"### {f.filename}（v{f.current_version}）")
            parts.append("")
            parts.append(f.content_md.rstrip("\n"))
    return "\n".join(parts) + "\n"


def _render_series_share_markdown(s: MeetingSeries) -> str:
    """业务线分享内容：元信息头 + 总精准需求 + 总业务事实（条目带来源行）。"""
    parts = [f"# 业务线汇总：{s.name}", ""]
    for kind in ("requirements", "facts"):
        doc = next((d for d in s.docs if d.kind == kind), None)
        parts.append(f"## {SERIES_DOC_TITLES[kind]}")
        parts.append("")
        if doc is None:
            parts.append("（尚未生成——由负责人在业务线详情页「从会议刷新汇总」后可见）")
        else:
            # 去掉渲染产物的标题行，正文并入本节
            body = _render_series_doc(doc, with_origin=True).split("\n", 1)[1]
            parts.append(body.strip("\n"))
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


@share_router.get("/{token}")
def share_meeting(token: str, kinds: str | None = None, db: Session = Depends(get_db)):
    """按 share_kinds 组装 LLM 可读 Markdown；?kinds=a,b 可临时覆盖。
    mt- 前缀命中会议；查不到再查业务线（ms- 前缀）→ 输出汇总文档。"""
    m = db.query(Meeting).filter(Meeting.share_token == token).first()
    if m is not None:
        if kinds:
            selected = [k.strip() for k in kinds.split(",") if k.strip()]
            selected = [k for k in selected if k in mp.ALL_KINDS]
        else:
            selected = json.loads(m.share_kinds_json or "[]")
        md = _render_share_markdown(m, selected)
        audit(db, f"share-…{token[-4:]}", "meeting_share_pull", f"meeting:{m.id}",
              {"kinds": selected})
        db.commit()
        return Response(content=md, media_type="text/markdown")
    s = db.query(MeetingSeries).filter(MeetingSeries.share_token == token).first()
    if s is not None:
        md = _render_series_share_markdown(s)
        audit(db, f"share-…{token[-4:]}", "series_share_pull", f"meeting_series:{s.id}", {})
        db.commit()
        return Response(content=md, media_type="text/markdown")
    raise HTTPException(status_code=404, detail="share token not found")


@share_router.get("/{token}/search")
def share_search(
    token: str, q: str = "", kind: str | None = None, db: Session = Depends(get_db)
):
    """该会议内的切块搜索（同享 token 授权范围）。"""
    m = _meeting_by_token(db, token)
    qy = (
        db.query(MeetingChunk, MeetingFile)
        .join(MeetingFile, MeetingChunk.file_id == MeetingFile.id)
        .filter(MeetingFile.meeting_id == m.id)
    )
    if q:
        qy = qy.filter(MeetingChunk.text_md.like(f"%{q}%"))
    if kind:
        qy = qy.filter(MeetingChunk.chunk_type == kind)
    results = []
    for chunk, file in qy.order_by(MeetingChunk.id).limit(200).all():
        results.append(
            {
                "chunk_id": chunk.id,
                "file_id": file.id,
                "filename": file.filename,
                "kind": file.kind,
                "meeting_id": m.id,
                "meeting_name": m.name,
                "section": chunk.section,
                "ref_id": chunk.ref_id,
                "chunk_type": chunk.chunk_type,
                "fields": json.loads(chunk.fields_json or "{}"),
                "text_md": chunk.text_md,
            }
        )
    return results
