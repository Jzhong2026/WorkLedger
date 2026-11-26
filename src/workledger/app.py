"""FastAPI application factory serving the Vue SPA + REST API."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import DatabaseError, close_connection, get_connection, init_db

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    task = asyncio.create_task(_sync_loop()) if settings.sync_interval_minutes > 0 else None
    yield
    if task:
        task.cancel()
    close_connection(settings.db_path)


async def _sync_loop():
    from .services import sync
    while True:
        await asyncio.sleep(settings.sync_interval_minutes * 60)
        try:
            await asyncio.to_thread(sync.sync_all, get_connection(settings.db_path))
        except Exception:
            # 单源失败已记入 sync_state；循环本身不能死
            continue


def create_app() -> FastAPI:
    app = FastAPI(title="WorkLedger", version="0.1.0", lifespan=lifespan)

    from .routers.api import router as api_router
    from .routers.learning import router as learning_router
    from .routers.sync import router as sync_router
    from .routers.work_items import router as work_items_router
    from .routers.work_review import router as work_review_router
    app.include_router(api_router, prefix="/api")
    app.include_router(work_items_router, prefix="/api")
    app.include_router(learning_router, prefix="/api")
    app.include_router(work_review_router, prefix="/api")
    app.include_router(sync_router, prefix="/api")

    @app.exception_handler(DatabaseError)
    async def db_error_handler(request: Request, exc: DatabaseError):
        status = exc.status_code or (503 if exc.retryable else 500)
        return JSONResponse(
            status_code=status,
            content={"error": str(exc), "retryable": exc.retryable, "db_path": exc.db_path},
        )

    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"error": "Build the frontend with npm ci and npm run build, then restart WorkLedger."},
        )

    return app


app = create_app()
