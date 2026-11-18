"""Project and Sprint CRUD for master data management."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from ..db import DatabaseError, write_transaction


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


# --- Projects ---

def create_project(conn: sqlite3.Connection, *, name: str, key: str, repo: str | None = None, description: str | None = None, color: str = "#2563eb") -> dict:
    now = _now()
    try:
        with write_transaction(conn):
            conn.execute(
                "INSERT INTO projects (name, key, repo, description, color, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (name, key.upper(), repo, description, color, now, now),
            )
            row = conn.execute("SELECT * FROM projects WHERE id = last_insert_rowid()").fetchone()
        return dict(row)
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise DatabaseError(f"Project key '{key}' already exists.", status_code=409) from e
        raise DatabaseError(f"Invalid project data: {e}", status_code=422) from e


def get_project(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def list_projects(conn: sqlite3.Connection, *, include_archived: bool = False) -> list[dict]:
    if include_archived:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    else:
        rows = conn.execute("SELECT * FROM projects WHERE is_archived = 0 ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def update_project(conn: sqlite3.Connection, project_id: int, **fields) -> dict | None:
    existing = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not existing:
        return None
    allowed = {"name", "key", "repo", "description", "color", "is_archived"}
    updates = {
        k: v for k, v in fields.items()
        if k in allowed and (v is not None or k in {"repo", "description"})
    }
    if not updates:
        return dict(existing)
    if "key" in updates:
        updates["key"] = updates["key"].upper()
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    try:
        with conn:
            conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", list(updates.values()) + [project_id])
    except sqlite3.IntegrityError as e:
        raise DatabaseError(f"Project key conflict: {e}", status_code=409) from e
    return get_project(conn, project_id)


def delete_project(conn: sqlite3.Connection, project_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return cur.rowcount > 0


# --- Sprints ---

def create_sprint(conn: sqlite3.Connection, *, project_id: int, name: str, start_date: str, end_date: str, goal: str | None = None, status: str = "planned") -> dict:
    proj = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not proj:
        raise DatabaseError(f"Project {project_id} not found.", status_code=404)
    if end_date < start_date:
        raise DatabaseError("End date must be on or after the start date.", status_code=422)
    now = _now()
    with conn:
        conn.execute(
            "INSERT INTO sprints (project_id, name, goal, start_date, end_date, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (project_id, name, goal, start_date, end_date, status, now, now),
        )
        row = conn.execute("SELECT * FROM sprints WHERE id = last_insert_rowid()").fetchone()
    return dict(row)


def get_sprint(conn: sqlite3.Connection, sprint_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    return dict(row) if row else None


def list_sprints(conn: sqlite3.Connection, *, project_id: int | None = None, status: str | None = None) -> list[dict]:
    conditions = []
    params: list = []
    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(f"SELECT * FROM sprints {where} ORDER BY start_date DESC", params).fetchall()
    return [dict(r) for r in rows]


def update_sprint(conn: sqlite3.Connection, sprint_id: int, **fields) -> dict | None:
    existing = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if not existing:
        return None
    allowed = {"name", "goal", "start_date", "end_date", "status"}
    updates = {
        k: v for k, v in fields.items() if k in allowed and (v is not None or k == "goal")
    }
    if not updates:
        return dict(existing)
    if updates.get("end_date", existing["end_date"]) < updates.get("start_date", existing["start_date"]):
        raise DatabaseError("End date must be on or after the start date.", status_code=422)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with conn:
        if updates.get("status") == "active":
            conn.execute(
                "UPDATE sprints SET status = 'planned' WHERE project_id = ? AND status = 'active' AND id != ?",
                (existing["project_id"], sprint_id),
            )
        conn.execute(f"UPDATE sprints SET {set_clause} WHERE id = ?", list(updates.values()) + [sprint_id])
    return get_sprint(conn, sprint_id)


def delete_sprint(conn: sqlite3.Connection, sprint_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM sprints WHERE id = ?", (sprint_id,))
    return cur.rowcount > 0
