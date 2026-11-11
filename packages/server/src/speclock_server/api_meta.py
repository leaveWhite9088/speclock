"""服务自身的状态：健康检查与版本。不需要 key，只对本机开放。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from speclock_config import __version__
from speclock_core import get_db
from speclock_server.deps import require_local_host
from speclock_server.responses import HealthOut

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(request: Request, db: Session = Depends(get_db)):
    """服务是否在运行、数据库能不能读，以及版本号。不需要 key；Host 不是本机地址时 403。
    数据库读不动时返回 503 + ``status: error``（版本号照给）。"""
    require_local_host(request)
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "version": __version__}, status_code=503)
    return {"status": "ok", "version": __version__}
