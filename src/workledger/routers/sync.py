"""Sync triggers, status, and health."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..config import settings
from ..db import DatabaseError, get_connection
from ..services import sync, sync_state

router = APIRouter(tags=["sync"])


def _conn():
    return get_connection(settings.db_path)


def _freshness(state: dict) -> dict:
    return {
        "last_sync_at": state["last_success_at"],
        "stale": sync_state.is_stale(state, settings.sync_interval_minutes),
        "last_error": state["last_error"],
    }


@router.get("/health")
def health():
    try:
        conn = _conn()
        conn.execute("SELECT 1")
        version = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        states = sync_state.get_states(conn)
    except DatabaseError as exc:
        return JSONResponse(status_code=503, content={"status": "error", "db": "error", "error": str(exc)})
    return {
        "status": "ok", "db": "ok", "schema_version": version, "version": "0.1.0",
        "sync": {source: _freshness(state) for source, state in states.items()},
    }


@router.get("/sync/status")
def sync_status():
    return {
        source: {**state, "stale": sync_state.is_stale(state, settings.sync_interval_minutes)}
        for source, state in sync_state.get_states(_conn()).items()
    }


def _run(result: dict) -> dict:
    if result.get("busy"):
        raise HTTPException(409, "Sync already in progress for this source.")
    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "Sync failed"))
    return result


@router.post("/sync/jira")
def trigger_jira():
    return _run(sync.run_locked("jira", sync.sync_jira.sync_jira, _conn()))


@router.post("/sync/bitbucket")
def trigger_bitbucket():
    return _run(sync.run_locked("bitbucket", sync.sync_bitbucket.sync_bitbucket, _conn()))


@router.post("/sync")
def trigger_all():
    result = sync.sync_all(_conn())
    if not result["ok"]:
        raise HTTPException(502, result)
    return result