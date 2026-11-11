"""网页自动登录：把**绑定了一个项目**的只读 key 交给本机上同源的网页。

网页只看得到一个项目：它用绑定了该项目的 ``viewer`` key 画界面，所以跨项目的内容它根本拿不到
（服务端的项目隔离对它和对 Agent 的 key 一视同仁）。只在请求来自本机地址（Host 是 127.0.0.1 /
localhost / ::1，挡 DNS 重绑定）且不是跨站请求时才给；给出去的 key 写不了任何东西。
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from sqlalchemy.orm import Session

from speclock_core import ApiError, Project, ensure_web_key, get_db
from speclock_server.deps import require_local_host
from speclock_server.responses import WebProjectOut, WebSessionOut

router = APIRouter(prefix="/api/v1", tags=["web"])


def _same_origin_local(request: Request) -> None:
    host = require_local_host(request)
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="不接受跨站请求")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="不接受跨站请求")


@router.get("/web/projects", response_model=list[WebProjectOut])
def web_projects(request: Request, db: Session = Depends(get_db)):
    """网页的项目选择页用：只有 id 和名称。嵌进别的页面时应当直接指明项目，不经过它。"""
    _same_origin_local(request)
    rows = db.query(Project).order_by(Project.id).all()
    return JSONResponse([{"id": p.id, "name": p.name} for p in rows], headers={"Cache-Control": "no-store"})


@router.get("/web/session", response_model=WebSessionOut)
def web_session(
    request: Request,
    project_id: int | None = Query(default=None, description="网页要看的项目；库里只有一个项目时可以不传"),
    db: Session = Depends(get_db),
):
    _same_origin_local(request)
    ids = [p.id for p in db.query(Project).order_by(Project.id).all()]
    if project_id is None:
        if len(ids) > 1:
            raise ApiError("web_project_required", "库里有多个项目，网页要指明看哪一个：地址后面加 ?project=<项目 id>")
        if not ids:
            raise HTTPException(status_code=404, detail="还没有项目：先运行 speclock init")
        project_id = ids[0]
    elif project_id not in ids:
        raise HTTPException(status_code=404, detail=f"没有项目 {project_id}")
    key = ensure_web_key(project_id)
    if key is None:
        raise HTTPException(status_code=404, detail="没有网页用的 key：先运行 speclock init / serve")
    return JSONResponse({"key": key, "project_id": project_id}, headers={"Cache-Control": "no-store"})
