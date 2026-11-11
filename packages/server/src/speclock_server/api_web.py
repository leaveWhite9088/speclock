"""网页自动登录：把只读 key 交给本机上同源的网页。

只在请求来自本机地址（Host 是 127.0.0.1 / localhost / ::1，挡 DNS 重绑定）且不是跨站请求
时才给；给出去的只是 ``viewer`` 角色的只读 key，写不了任何东西。
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from speclock_config import read_web_key

router = APIRouter(prefix="/api/v1", tags=["web"])

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@router.get("/web/session")
def web_session(request: Request):
    host = request.headers.get("host", "")
    if urlparse(f"//{host}").hostname not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="只对本机地址开放")
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="不接受跨站请求")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="不接受跨站请求")
    key = read_web_key()
    if key is None:
        raise HTTPException(status_code=404, detail="没有网页用的 key：先运行 speclock init / serve")
    return JSONResponse({"key": key}, headers={"Cache-Control": "no-store"})
