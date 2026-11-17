"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .db import DatabaseError, close_connection, init_db

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    yield
    close_connection(settings.db_path)


def create_app() -> FastAPI:
    app = FastAPI(title="WorkLedger", version="0.1.0", lifespan=lifespan)

    from .routers.api import router as api_router
    from .routers.web import router as web_router

    app.include_router(api_router, prefix="/api")
    app.include_router(web_router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(DatabaseError)
    async def db_error_handler(request: Request, exc: DatabaseError):
        status = 503 if exc.retryable else 500
        return JSONResponse(
            status_code=status,
            content={
                "error": str(exc),
                "retryable": exc.retryable,
                "db_path": exc.db_path,
            },
        )

    return app


app = create_app()