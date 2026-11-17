"""Quick inbox: capture raw notes, structure via agent, confirm drafts into events."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..db import DatabaseError
from ..schemas import EventCreate
from . import events


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def create_note(conn: sqlite3.Connection, raw_text: str) -> dict:
    now = _now()
    with conn:
        conn.execute(
            "INSERT INTO inbox_notes (raw_text, status, created_at, updated_at) VALUES (?, 'raw', ?, ?)",
            (raw_text, now, now),
        )
        row = conn.execute("SELECT * FROM inbox_notes WHERE id = last_insert_rowid()").fetchone()
    return dict(row)


def list_notes(conn: sqlite3.Connection, *, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute("SELECT * FROM inbox_notes WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM inbox_notes ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM inbox_notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def save_drafts(conn: sqlite3.Connection, note_id: int, draft_events: list[dict]) -> list[dict]:
    note = get_note(conn, note_id)
    if not note:
        raise DatabaseError(f"Note {note_id} not found.")
    now = _now()
    drafts = []
    with conn:
        for ev in draft_events:
            conn.execute(
                "INSERT INTO event_drafts (note_id, draft_json, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
                (note_id, json.dumps(ev, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM event_drafts WHERE id = last_insert_rowid()").fetchone()
            drafts.append(dict(row))
        conn.execute("UPDATE inbox_notes SET status = 'structured', updated_at = ? WHERE id = ?", (now, note_id))
    return drafts


def list_drafts(conn: sqlite3.Connection, *, note_id: int | None = None, status: str | None = "pending") -> list[dict]:
    conditions = []
    params: list = []
    if note_id is not None:
        conditions.append("note_id = ?")
        params.append(note_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(f"SELECT * FROM event_drafts {where} ORDER BY id DESC", params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["draft"] = json.loads(d["draft_json"])
        result.append(d)
    return result


def confirm_draft(conn: sqlite3.Connection, draft_id: int) -> dict:
    row = conn.execute("SELECT * FROM event_drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        raise DatabaseError(f"Draft {draft_id} not found.")
    if row["status"] != "pending":
        raise DatabaseError(f"Draft {draft_id} already {row['status']}.")
    draft = json.loads(row["draft_json"])
    draft.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
    data = EventCreate(**draft)
    event = events.create_event(conn, data)
    now = _now()
    with conn:
        conn.execute(
            "UPDATE event_drafts SET status = 'confirmed', committed_event_id = ?, updated_at = ? WHERE id = ?",
            (event["id"], now, draft_id),
        )
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM event_drafts WHERE note_id = ? AND status = 'pending'", (row["note_id"],)
        ).fetchone()["c"]
        if remaining == 0:
            conn.execute("UPDATE inbox_notes SET status = 'committed', updated_at = ? WHERE id = ?", (now, row["note_id"]))
    return {"draft_id": draft_id, "event": event}


def discard_draft(conn: sqlite3.Connection, draft_id: int) -> bool:
    with conn:
        cur = conn.execute("UPDATE event_drafts SET status = 'discarded', updated_at = ? WHERE id = ? AND status = 'pending'", (_now(), draft_id))
    return cur.rowcount > 0


def discard_note(conn: sqlite3.Connection, note_id: int) -> bool:
    with conn:
        cur = conn.execute("UPDATE inbox_notes SET status = 'discarded', updated_at = ? WHERE id = ?", (_now(), note_id))
    return cur.rowcount > 0