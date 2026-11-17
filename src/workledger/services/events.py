"""Work event CRUD with source-based deduplication."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from ..db import DatabaseError
from ..schemas import EventCreate, EventUpdate


def _make_source_key(data: EventCreate) -> str:
    if data.source_key:
        return data.source_key
    parts = [data.event_type]
    if data.repo:
        parts.append(data.repo)
    if data.pr_number is not None:
        parts.append(str(data.pr_number))
    if data.comment_id:
        parts.append(data.comment_id)
    if len(parts) == 1:
        parts.append(uuid.uuid4().hex)
    return ":".join(parts)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("root_cause_confirmed", "verification_done", "user_edited"):
        d[k] = bool(d[k])
    return d


def create_event(conn: sqlite3.Connection, data: EventCreate) -> dict:
    source_key = _make_source_key(data)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    occurred = data.occurred_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with conn:
            existing = conn.execute(
                "SELECT * FROM work_events WHERE source_key = ?", (source_key,)
            ).fetchone()
            if existing:
                return _row_to_dict(existing)

            conn.execute(
                """INSERT INTO work_events
                   (event_type, occurred_at, recorded_at, repo, pr_number, comment_id,
                    jira_key, source_key, source_agent, summary, detail, evidence_url,
                    root_cause, root_cause_confirmed, verification_result, verification_done,
                    reply_status, extra_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.event_type, occurred, now, data.repo, data.pr_number,
                    data.comment_id, data.jira_key, source_key, data.source_agent,
                    data.summary, data.detail, data.evidence_url,
                    data.root_cause, int(data.root_cause_confirmed),
                    data.verification_result, int(data.verification_done),
                    data.reply_status, data.extra_json, now, now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM work_events WHERE source_key = ?", (source_key,)
            ).fetchone()
            return _row_to_dict(row)
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            row = conn.execute(
                "SELECT * FROM work_events WHERE source_key = ?", (source_key,)
            ).fetchone()
            if row:
                return _row_to_dict(row)
        raise DatabaseError(f"Invalid event data: {e}") from e
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "busy" in str(e).lower():
            raise DatabaseError("Database locked, retry shortly.", retryable=True) from e
        raise DatabaseError(f"Write failed: {e}") from e


def get_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM work_events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_event(conn: sqlite3.Connection, event_id: int, data: EventUpdate, changed_by: str = "user") -> dict | None:
    existing = conn.execute("SELECT * FROM work_events WHERE id = ?", (event_id,)).fetchone()
    if not existing:
        return None

    updates = data.model_dump(exclude_none=True)
    if not updates:
        return _row_to_dict(existing)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    set_clauses = []
    params = []
    for field, value in updates.items():
        if field in ("root_cause_confirmed", "verification_done"):
            value = int(value)
        set_clauses.append(f"{field} = ?")
        params.append(value)
        conn.execute(
            "INSERT INTO revisions (entity_type, entity_id, field_name, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
            ("work_event", event_id, field, str(existing[field]), str(value), changed_by),
        )

    set_clauses.extend(["user_edited = 1", "updated_at = ?"])
    params.extend([now, event_id])

    with conn:
        conn.execute(
            f"UPDATE work_events SET {', '.join(set_clauses)} WHERE id = ?", params
        )
    return get_event(conn, event_id)


def search_events(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    jira_key: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []

    if q:
        conditions.append("(summary LIKE ? OR detail LIKE ? OR root_cause LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if repo:
        conditions.append("repo = ?")
        params.append(repo)
    if pr_number is not None:
        conditions.append("pr_number = ?")
        params.append(pr_number)
    if jira_key:
        conditions.append("jira_key = ?")
        params.append(jira_key)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if date_from:
        conditions.append("occurred_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("occurred_at <= ?")
        params.append(date_to + " 23:59:59")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) AS c FROM work_events {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM work_events {where} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_row_to_dict(r) for r in rows], total


def get_pr_timeline(conn: sqlite3.Connection, repo: str, pr_number: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM work_events WHERE repo = ? AND pr_number = ? ORDER BY occurred_at ASC, id ASC",
        (repo, pr_number),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_repos(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT repo FROM work_events WHERE repo IS NOT NULL ORDER BY repo"
    ).fetchall()
    return [r["repo"] for r in rows]