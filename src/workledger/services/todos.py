"""Todo CRUD with status rules shared by Web and MCP."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..db import DatabaseError
from ..schemas import TodoCreate, TodoUpdate


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def create_todo(conn: sqlite3.Connection, data: TodoCreate) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if data.source_key:
        existing = conn.execute(
            "SELECT * FROM todos WHERE source_key = ?", (data.source_key,)
        ).fetchone()
        if existing:
            return _row_to_dict(existing)

    if data.event_id is not None:
        ev = conn.execute("SELECT id FROM work_events WHERE id = ?", (data.event_id,)).fetchone()
        if not ev:
            raise DatabaseError(f"Event {data.event_id} not found. Cannot link todo.")

    completed_at = now if data.status == "done" else None
    try:
        with conn:
            conn.execute(
                """INSERT INTO todos
                   (title, description, status, event_id, wait_target,
                    due_date, next_followup, completed_at, source_key, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.title, data.description, data.status, data.event_id,
                    data.wait_target, data.due_date, data.next_followup,
                    completed_at, data.source_key, now, now,
                ),
            )
            row = conn.execute("SELECT * FROM todos WHERE id = last_insert_rowid()").fetchone()
            return _row_to_dict(row)
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e) and data.source_key:
            row = conn.execute(
                "SELECT * FROM todos WHERE source_key = ?", (data.source_key,)
            ).fetchone()
            if row:
                return _row_to_dict(row)
        raise DatabaseError(f"Invalid todo data: {e}") from e


def get_todo(conn: sqlite3.Connection, todo_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_todo(conn: sqlite3.Connection, todo_id: int, data: TodoUpdate) -> dict | None:
    existing = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if not existing:
        return None

    updates = data.model_dump(exclude_none=True)
    if not updates:
        return _row_to_dict(existing)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if "status" in updates:
        if updates["status"] == "done" and existing["status"] != "done":
            updates["completed_at"] = now
        elif updates["status"] != "done" and existing["status"] == "done":
            updates["completed_at"] = None

    set_clauses = [f"{k} = ?" for k in updates]
    set_clauses.append("updated_at = ?")
    params = list(updates.values()) + [now, todo_id]

    with conn:
        conn.execute(f"UPDATE todos SET {', '.join(set_clauses)} WHERE id = ?", params)
    return get_todo(conn, todo_id)


def list_todos(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    due_today: str | None = None,
    followup_today: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if due_today:
        conditions.append("due_date <= ? AND status != 'done'")
        params.append(due_today)
    if followup_today:
        conditions.append("next_followup <= ? AND status != 'done'")
        params.append(followup_today)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM todos {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM todos {where} ORDER BY "
        "CASE status WHEN 'pending' THEN 0 WHEN 'waiting' THEN 1 ELSE 2 END, "
        "COALESCE(next_followup, due_date, '9999') ASC, id ASC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_row_to_dict(r) for r in rows], total


def today_todos(conn: sqlite3.Connection, today: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM todos
           WHERE status != 'done'
             AND (due_date <= ? OR next_followup <= ? OR (due_date IS NULL AND next_followup IS NULL))
           ORDER BY
             CASE WHEN due_date <= ? THEN 0 WHEN next_followup <= ? THEN 1 ELSE 2 END,
             COALESCE(due_date, next_followup, '9999') ASC, id ASC""",
        (today, today, today, today),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cur.rowcount > 0