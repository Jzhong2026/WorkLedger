"""Sync freshness bookkeeping."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ..db import write_transaction


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record_attempt(conn: sqlite3.Connection, source: str) -> None:
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at) VALUES (?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at",
            (source, utc_now_iso()),
        )


def record_success(conn: sqlite3.Connection, source: str, detail: dict) -> None:
    now = utc_now_iso()
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at, last_success_at, last_error, detail_json) "
            "VALUES (?, ?, ?, NULL, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, "
            "last_success_at=excluded.last_success_at, last_error=NULL, detail_json=excluded.detail_json",
            (source, now, now, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )


def record_error(conn: sqlite3.Connection, source: str, error: str) -> None:
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at, last_error) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, "
            "last_error=excluded.last_error",
            (source, utc_now_iso(), error[:2000]),
        )


def get_states(conn: sqlite3.Connection) -> dict[str, dict]:
    states = {}
    for row in conn.execute("SELECT * FROM sync_state ORDER BY source"):
        state = dict(row)
        state["detail"] = json.loads(state.pop("detail_json") or "{}")
        states[state["source"]] = state
    return states


def is_stale(state: dict | None, interval_minutes: int) -> bool:
    if not state or not state.get("last_success_at"):
        return True
    last = datetime.fromisoformat(state["last_success_at"])
    threshold = max(2 * interval_minutes, 30) if interval_minutes > 0 else 24 * 60
    return (datetime.now(UTC) - last).total_seconds() / 60 > threshold
