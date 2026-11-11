"""FastAPI application assembly: admin (read / manage) + change-request (the only
write channel) + agent (read) JSON APIs.

When the Vue SPA has been built (``apps/web/dist/``), it is
served from the same process: static bundles under ``/assets`` and every
non-API GET falls back to ``index.html`` so client-side routes (deep links
like ``/proposals``) work. Unknown ``/api/`` paths still get a JSON 404.
Without a built SPA the app is a pure JSON API (tests, API-only deploys).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from speclock_config import __version__, embed_origins
from speclock_core import code_of, init_db
from speclock_server import api_admin, api_agent, api_cr, api_exec, api_meta, api_search, api_web
from speclock_server.responses import ERROR_RESPONSES

BASE_DIR = Path(__file__).resolve().parent
# 网页构建产物：开发时在 monorepo 的 apps/web/dist（packages/server/src/speclock_server 往上 4 层是仓库根）；
# 部署到别处时用环境变量 SPECLOCK_WEB_DIST 指过去
DIST_DIR = Path(os.environ.get("SPECLOCK_WEB_DIST") or BASE_DIR.parents[3] / "apps" / "web" / "dist")
STATIC_DIR = BASE_DIR / "static"


NO_WEB_PAGE = """<!doctype html><meta charset="utf-8"><title>SpecLock</title>
<body style="font:16px/1.6 system-ui;max-width:42rem;margin:4rem auto;padding:0 1rem">
<h1>SpecLock 服务在运行</h1>
<p>但这份代码里没有构建好的网页（<code>apps/web/dist/</code>）。要看网页，先构建一次：</p>
<pre>cd apps/web &amp;&amp; npm install &amp;&amp; npm run build</pre>
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

    @app.exception_handler(StarletteHTTPException)
    async def http_errors(request, exc):
        # 所有错误都是 {"detail": ..., "code": ...}：detail 给人看（保持原样），code 给程序判断（见 speclock_core.errors）
        detail = exc.detail
        if exc.status_code == 400 and detail == "There was an error parsing the body":
            # FastAPI 对「请求体不是合法 JSON」只说 error parsing the body，没说是编码问题（Windows 下 curl 常见）
            detail = ("请求体不是有效的 UTF-8 JSON；含中文时请用 UTF-8 编码"
                      "（curl 用 --data-binary @文件.json，不要在命令行里直接写中文）")
        return JSONResponse({"detail": detail, "code": code_of(exc)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_errors(request, exc):
        return JSONResponse({"detail": jsonable_encoder(exc.errors()), "code": "validation_failed"},
                            status_code=422)

    frame_ancestors = "frame-ancestors 'self' " + " ".join(embed_origins())

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

    app.include_router(api_meta.router)
    for module in (api_admin, api_cr, api_agent, api_exec, api_search, api_web):
        app.include_router(module.router, responses=ERROR_RESPONSES)

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
                return JSONResponse({"detail": "Not Found", "code": "not_found"}, status_code=404)
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

    from speclock_config import ensure_keys_dir, find_home, load_config, locate_home
    from speclock_core import get_engine, retire_global_web_key

    cfg = load_config()
    found, how = locate_home()
    if found is not None:
        print(f"SpecLock 数据目录：{found}（{how}）")
        if how.startswith("上层目录"):
            print("注意：用的是上层目录的数据，不是当前目录的。想在这里用独立的一份，先运行 speclock init。")
    get_engine()
    init_db()
    retire_global_web_key()  # 旧版给网页发的全局只读 key（能看全部项目）：清掉；网页现在按项目各用一把绑定项目的 key
    home = find_home()
    if home is not None:
        ensure_keys_dir(home)
    uvicorn.run("speclock_server.main:app", host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    run()
