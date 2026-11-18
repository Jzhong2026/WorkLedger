"""Todo CRUD with status rules shared by Web and MCP."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from ..db import DatabaseError
from ..schemas import TodoCreate, TodoUpdate


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def create_todo(conn: sqlite3.Connection, data: TodoCreate) -> dict:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

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
    updates = data.model_dump(exclude_unset=True)
    for required in ("title", "status"):
        if updates.get(required) is None:
            updates.pop(required, None)
    if not updates:
        return get_todo(conn, todo_id)

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    set_clauses = [f"{field} = ?" for field in updates]
    params = list(updates.values())

    if "status" in updates:
        if updates["status"] == "done":
            set_clauses.append("completed_at = COALESCE(completed_at, ?)")
            params.append(now)
        else:
            set_clauses.append("completed_at = NULL")
    set_clauses.append("updated_at = ?")
    params.extend((now, todo_id))

    try:
        with conn:
            row = conn.execute(
                f"UPDATE todos SET {', '.join(set_clauses)} WHERE id = ? RETURNING *", params,
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise DatabaseError(f"Invalid todo data: {exc}") from exc
    return _row_to_dict(row) if row else None


def list_todos(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    due_today: str | None = None,
    followup_today: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []

    if status:
        conditions.append("t.status = ?")
        params.append(status)
    if due_today:
        conditions.append("t.due_date <= ? AND t.status != 'done'")
        params.append(due_today)
    if followup_today:
        conditions.append("t.next_followup <= ? AND t.status != 'done'")
        params.append(followup_today)
    if date_from:
        conditions.append("t.created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("t.created_at <= ?")
        params.append(f"{date_to} 23:59:59")
    source = "FROM todos t"
    if project_id is not None:
        source += " LEFT JOIN work_events e ON t.event_id = e.id"
        if project_id == 0:
            conditions.append("COALESCE(t.project_id, e.project_id) IS NULL")
        else:
            conditions.append("COALESCE(t.project_id, e.project_id) = ?")
            params.append(project_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) AS c {source} {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT t.* {source} {where} ORDER BY "
        "CASE t.status WHEN 'pending' THEN 0 WHEN 'waiting' THEN 1 ELSE 2 END, "
        "COALESCE(t.next_followup, t.due_date, '9999') ASC, t.id ASC LIMIT ? OFFSET ?",
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


def today_summary(conn: sqlite3.Connection, today: str) -> dict:
    counts = {"pending": 0, "waiting": 0, "done": 0}
    groups: dict[str, list[dict]] = {"overdue": [], "today": [], "unscheduled": []}
    conn.execute("SAVEPOINT todo_summary")
    try:
        for row in conn.execute("SELECT status, COUNT(*) AS count FROM todos GROUP BY status"):
            counts[row["status"]] = row["count"]

        for item in today_todos(conn, today):
            dates = [value for value in (item["due_date"], item["next_followup"]) if value]
            if not dates:
                groups["unscheduled"].append(item)
            elif min(dates) < today:
                groups["overdue"].append(item)
            else:
                groups["today"].append(item)
    finally:
        conn.execute("RELEASE SAVEPOINT todo_summary")
    return {"today": today, "counts": counts, "groups": groups}


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cur.rowcount > 0
