"""FastAPI application assembly: admin (write) + agent (read) + UI routers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from speclock import api_admin, api_agent, ui
from speclock.db import init_db

BASE_DIR = Path(__file__).parent


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
    app.include_router(ui.router)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    return app


app = create_app()
