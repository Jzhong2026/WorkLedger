"""Project summary endpoint for assistants."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import get_connection
from ..services import summary

router = APIRouter(tags=["summary"])


def _conn():
    return get_connection(settings.db_path)


@router.get("/summary/project")
def get_project_summary(key: str, window: str = "7d"):
    try:
        return summary.project_summary(_conn(), key, window)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))