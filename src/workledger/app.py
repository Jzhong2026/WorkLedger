"""FastAPI application factory serving the Vue SPA + REST API."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import DatabaseError, close_connection, init_db

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    yield
    close_connection(settings.db_path)


def create_app() -> FastAPI:
    app = FastAPI(title="WorkLedger", version="0.1.0", lifespan=lifespan)

    from .routers.api import router as api_router
    app.include_router(api_router, prefix="/api")

    @app.exception_handler(DatabaseError)
    async def db_error_handler(request: Request, exc: DatabaseError):
        status = 503 if exc.retryable else 500
        return JSONResponse(
            status_code=status,
            content={"error": str(exc), "retryable": exc.retryable, "db_path": exc.db_path},
        )

    if (FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api"):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"error": "Frontend not built. Run: cd frontend && npm install && npm run build"},
        )

    return app


app = create_app()