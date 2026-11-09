"""FastAPI application assembly: admin (read / manage) + change-request (the only
write channel) + agent (read) JSON APIs.

When the Vue SPA has been built (``web/dist/`` next to the package), it is
served from the same process: static bundles under ``/assets`` and every
non-API GET falls back to ``index.html`` so client-side routes (deep links
like ``/proposals``) work. Unknown ``/api/`` paths still get a JSON 404.
Without a built SPA the app is a pure JSON API (tests, API-only deploys).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from speclock import __version__, home, api_admin, api_agent, api_cr, api_exec, api_search, api_web
from speclock.db import init_db

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "web" / "dist"
STATIC_DIR = BASE_DIR / "static"


NO_WEB_PAGE = """<!doctype html><meta charset="utf-8"><title>SpecLock</title>
<body style="font:16px/1.6 system-ui;max-width:42rem;margin:4rem auto;padding:0 1rem">
<h1>SpecLock 服务在运行</h1>
<p>但这份代码里没有构建好的网页（<code>web/dist/</code>）。要看网页，先构建一次：</p>
<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>构建完刷新本页即可。接口文档在 <a href="/docs">/docs</a>。</p>"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="SpecLock",
        version=__version__,
        description=(
            "Single source of truth for business specs. Agents read published "
            "versions; the only write channel is a human-approved Change Request "
            "followed by Commits from a requirements agent."
        ),
    )
    init_db()

    frame_ancestors = "frame-ancestors 'self' " + " ".join(home.embed_origins())

    @app.middleware("http")
    async def allow_embedding(request, call_next):
        # 网页可以被嵌进别的页面（见 docs/EMBED.md），但只有配置里允许的来源才行，防止被恶意页面套壳
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = frame_ancestors
        return response

    @app.get("/embed.js", include_in_schema=False)
    def embed_js():
        return FileResponse(STATIC_DIR / "embed.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})

    app.include_router(api_admin.router)
    app.include_router(api_cr.router)
    app.include_router(api_agent.router)
    app.include_router(api_exec.router)
    app.include_router(api_search.router)
    app.include_router(api_web.router)

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
    else:
        @app.get("/", include_in_schema=False)
        def no_web():
            return HTMLResponse(NO_WEB_PAGE)

    return app


app = create_app()


def run() -> None:
    """按 .speclock/config.toml 的 host / port 启动服务。"""
    import uvicorn

    from speclock.settings import load_settings

    s = load_settings()
    from speclock.db import get_engine, init_db
    from speclock.webkey import ensure_web_key

    get_engine()
    init_db()
    ensure_web_key()  # 网页用的只读 key，缺了就补
    from speclock.home import find_home
    from speclock.keyfiles import ensure_keys_dir

    home = find_home()
    if home is not None:
        ensure_keys_dir(home)
    uvicorn.run("speclock.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    run()
