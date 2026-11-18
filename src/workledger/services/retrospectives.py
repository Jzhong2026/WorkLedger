"""Accomplishments and cases CRUD for retrospectives."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from ..db import DatabaseError
from ..schemas import AccomplishmentCreate, AccomplishmentUpdate, CaseCreate, CaseUpdate


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _bool_fields(d: dict, fields: tuple[str, ...]) -> dict:
    for k in fields:
        if k in d:
            d[k] = bool(d[k])
    return d


def _check_source_event(conn: sqlite3.Connection, event_id: int | None) -> None:
    if event_id is not None and not conn.execute(
        "SELECT 1 FROM work_events WHERE id = ?", (event_id,)
    ).fetchone():
        raise DatabaseError(f"Source event {event_id} not found.", status_code=404)


# --- Accomplishments ---

def create_accomplishment(conn: sqlite3.Connection, data: AccomplishmentCreate) -> dict:
    now = _now()
    occurred = data.occurred_at.strftime("%Y-%m-%d %H:%M:%S")

    if data.source_key:
        existing = conn.execute(
            "SELECT * FROM accomplishments WHERE source_key = ?", (data.source_key,)
        ).fetchone()
        if existing:
            return _bool_fields(dict(existing), ("is_highlight", "user_edited"))

    with conn:
        _check_source_event(conn, data.event_id)
        conn.execute(
            """INSERT INTO accomplishments
               (title, description, occurred_at, impact, impact_evidence_url,
                is_highlight, tags, source_key, created_at, updated_at, event_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.title, data.description, occurred, data.impact,
                data.impact_evidence_url, int(data.is_highlight), data.tags,
                data.source_key, now, now, data.event_id,
            ),
        )
        row = conn.execute("SELECT * FROM accomplishments WHERE id = last_insert_rowid()").fetchone()
    return _bool_fields(dict(row), ("is_highlight", "user_edited"))


def get_accomplishment(conn: sqlite3.Connection, acc_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM accomplishments WHERE id = ?", (acc_id,)).fetchone()
    return _bool_fields(dict(row), ("is_highlight", "user_edited")) if row else None


def update_accomplishment(conn: sqlite3.Connection, acc_id: int, data: AccomplishmentUpdate, changed_by: str = "user") -> dict | None:
    existing = conn.execute("SELECT * FROM accomplishments WHERE id = ?", (acc_id,)).fetchone()
    if not existing:
        return None
    updates = data.model_dump(exclude_none=True)
    if not updates:
        return _bool_fields(dict(existing), ("is_highlight", "user_edited"))

    now = _now()
    set_clauses = []
    params = []
    for field, value in updates.items():
        if field == "is_highlight":
            value = int(value)
        set_clauses.append(f"{field} = ?")
        params.append(value)
    set_clauses.extend(["user_edited = 1", "updated_at = ?"])
    params.extend([now, acc_id])
    with conn:
        for field, value in updates.items():
            if field == "is_highlight":
                value = int(value)
            conn.execute(
                "INSERT INTO revisions (entity_type, entity_id, field_name, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
                ("accomplishment", acc_id, field, str(existing[field]), str(value), changed_by),
            )
        conn.execute(f"UPDATE accomplishments SET {', '.join(set_clauses)} WHERE id = ?", params)
    return get_accomplishment(conn, acc_id)


def list_accomplishments(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    highlight_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []
    if date_from:
        conditions.append("occurred_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("occurred_at <= ?")
        params.append(date_to + " 23:59:59")
    if highlight_only:
        conditions.append("is_highlight = 1")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM accomplishments {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM accomplishments {where} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_bool_fields(dict(r), ("is_highlight", "user_edited")) for r in rows], total


# --- Cases ---

def create_case(conn: sqlite3.Connection, data: CaseCreate) -> dict:
    now = _now()
    occurred = data.occurred_at.strftime("%Y-%m-%d %H:%M:%S")

    if data.source_key:
        existing = conn.execute("SELECT * FROM cases WHERE source_key = ?", (data.source_key,)).fetchone()
        if existing:
            return _bool_fields(dict(existing), ("root_cause_confirmed", "verification_done", "user_edited"))

    with conn:
        _check_source_event(conn, data.event_id)
        conn.execute(
            """INSERT INTO cases
               (title, phenomenon, root_cause, root_cause_confirmed, solution,
                verification, verification_done, occurred_at, tags, source_key, created_at,
                updated_at, event_id, evidence_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data.title, data.phenomenon, data.root_cause, int(data.root_cause_confirmed),
                data.solution, data.verification, int(data.verification_done),
                occurred, data.tags, data.source_key, now, now, data.event_id, data.evidence_url,
            ),
        )
        row = conn.execute("SELECT * FROM cases WHERE id = last_insert_rowid()").fetchone()
    return _bool_fields(dict(row), ("root_cause_confirmed", "verification_done", "user_edited"))


def get_case(conn: sqlite3.Connection, case_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _bool_fields(dict(row), ("root_cause_confirmed", "verification_done", "user_edited")) if row else None


def update_case(conn: sqlite3.Connection, case_id: int, data: CaseUpdate, changed_by: str = "user") -> dict | None:
    existing = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not existing:
        return None
    updates = data.model_dump(exclude_none=True)
    if not updates:
        return _bool_fields(dict(existing), ("root_cause_confirmed", "verification_done", "user_edited"))

    now = _now()
    set_clauses = []
    params = []
    for field, value in updates.items():
        if field in ("root_cause_confirmed", "verification_done"):
            value = int(value)
        set_clauses.append(f"{field} = ?")
        params.append(value)
    set_clauses.extend(["user_edited = 1", "updated_at = ?"])
    params.extend([now, case_id])
    with conn:
        for field, value in updates.items():
            if field in ("root_cause_confirmed", "verification_done"):
                value = int(value)
            conn.execute(
                "INSERT INTO revisions (entity_type, entity_id, field_name, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
                ("case", case_id, field, str(existing[field]), str(value), changed_by),
            )
        conn.execute(f"UPDATE cases SET {', '.join(set_clauses)} WHERE id = ?", params)
    return get_case(conn, case_id)


def list_cases(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []
    if date_from:
        conditions.append("occurred_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("occurred_at <= ?")
        params.append(date_to + " 23:59:59")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM cases {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM cases {where} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_bool_fields(dict(r), ("root_cause_confirmed", "verification_done", "user_edited")) for r in rows], total
