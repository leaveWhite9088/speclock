"""FastAPI application assembly: admin (write) + agent (read) JSON APIs.

When the Vue SPA has been built (``web/dist/`` next to the package), it is
served from the same process: static bundles under ``/assets`` and every
non-API GET falls back to ``index.html`` so client-side routes (deep links
like ``/proposals``) work. Unknown ``/api/`` paths still get a JSON 404.
Without a built SPA the app is a pure JSON API (tests, API-only deploys).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from speclock import api_admin, api_agent, api_meetings
from speclock.db import init_db

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="SpecLock",
        version="0.1.0",
        description=(
            "Single source of truth for business docs. Agents read published "
            "versions through a physically read-only API; the only write "
            "outlet is the proposal channel."
        ),
    )
    init_db()
    app.include_router(api_admin.router)
    app.include_router(api_agent.router)
    app.include_router(api_meetings.admin_router)
    app.include_router(api_meetings.share_router)

    if DIST_DIR.is_dir():
        index_html = DIST_DIR / "index.html"
        app.mount(
            "/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets"
        )

        # Registered last, after every API route and /docs: FastAPI matches
        # routes in registration order, so the catch-all only sees paths no
        # real route claimed.
        @app.get("/", include_in_schema=False)
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str = ""):
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(index_html)

    return app


app = create_app()


def run() -> None:
    """按 speclock.toml 当前环境（active / SPECLOCK_ENV）启动服务。"""
    import uvicorn

    from speclock.settings import load_settings

    s = load_settings()
    uvicorn.run("speclock.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    run()
