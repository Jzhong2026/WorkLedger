"""Quick inbox: capture raw notes, structure via agent, confirm drafts into events."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from pydantic import ValidationError

from ..db import DatabaseError, write_transaction
from ..schemas import EventCreate, EventDraftUpdate
from . import events


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def create_note(conn: sqlite3.Connection, raw_text: str) -> dict:
    if not raw_text.strip():
        raise DatabaseError("A note needs some text.", status_code=422)
    now = _now()
    with write_transaction(conn):
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


def _require_note(conn: sqlite3.Connection, note_id: int) -> dict:
    note = get_note(conn, note_id)
    if not note:
        raise DatabaseError(f"Note {note_id} not found.", status_code=404)
    return note


def _require_raw_note(note: dict) -> None:
    if note["status"] != "raw":
        raise DatabaseError(
            f"Note {note['id']} is already {note['status']}. Refresh the inbox and review its state.",
            status_code=409,
        )


def _draft_to_dict(row: sqlite3.Row) -> dict:
    return {**dict(row), "draft": json.loads(row["draft_json"])}


def _get_draft(conn: sqlite3.Connection, draft_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM event_drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        raise DatabaseError(f"Draft {draft_id} not found.", status_code=404)
    return row


def _reviewed_draft(payload: dict) -> dict:
    try:
        draft = EventDraftUpdate.model_validate(payload)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        field = ".".join(str(part) for part in error["loc"])
        raise DatabaseError(f"Invalid draft field {field}: {error['msg']}", status_code=422) from exc
    if not draft.event_type or not (draft.summary or "").strip():
        raise DatabaseError("A draft needs an event type and a summary.", status_code=422)
    return draft.model_dump(mode="json", exclude_unset=True)


def _insert_draft(conn: sqlite3.Connection, note_id: int, draft: dict) -> sqlite3.Row:
    now = _now()
    cursor = conn.execute(
        """INSERT INTO event_drafts (note_id, draft_json, status, created_at, updated_at)
           VALUES (?, ?, 'pending', ?, ?)""",
        (note_id, json.dumps(draft, ensure_ascii=False), now, now),
    )
    return _get_draft(conn, cursor.lastrowid)


def save_drafts(conn: sqlite3.Connection, note_id: int, draft_events: list[dict]) -> list[dict]:
    with write_transaction(conn):
        _require_raw_note(_require_note(conn, note_id))
        if not draft_events:
            return []

        drafts = [_draft_to_dict(_insert_draft(conn, note_id, _reviewed_draft(ev))) for ev in draft_events]
        conn.execute(
            "UPDATE inbox_notes SET status = 'structured', updated_at = ? WHERE id = ?",
            (_now(), note_id),
        )
        return drafts


def list_drafts(
    conn: sqlite3.Connection, *, note_id: int | None = None, status: str | None = "pending",
) -> list[dict]:
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
    return [_draft_to_dict(row) for row in rows]


def _review_changes(row: sqlite3.Row, changes: EventDraftUpdate | None) -> dict:
    payload = json.loads(row["draft_json"])
    if changes is not None:
        payload.update(changes.model_dump(exclude_unset=True))
    return _reviewed_draft(payload)


def update_draft(conn: sqlite3.Connection, draft_id: int, changes: EventDraftUpdate) -> dict:
    with write_transaction(conn):
        row = _get_draft(conn, draft_id)
        if row["status"] != "pending":
            raise DatabaseError(f"Draft {draft_id} is already {row['status']}.", status_code=409)
        draft = _review_changes(row, changes)
        conn.execute(
            "UPDATE event_drafts SET draft_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(draft, ensure_ascii=False), _now(), draft_id),
        )
        return _draft_to_dict(_get_draft(conn, draft_id))


def _sync_note_status(conn: sqlite3.Connection, note_id: int | None) -> None:
    conn.execute(
        """UPDATE inbox_notes
           SET status = CASE
               WHEN EXISTS (
                   SELECT 1 FROM event_drafts WHERE note_id = inbox_notes.id AND status = 'pending'
               ) THEN 'structured'
               WHEN EXISTS (
                   SELECT 1 FROM event_drafts WHERE note_id = inbox_notes.id AND status = 'confirmed'
               ) THEN 'committed'
               ELSE 'raw'
           END, updated_at = ?
           WHERE id = ? AND status != 'discarded'""",
        (_now(), note_id),
    )


def _confirmed_result(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    event = events.get_event(conn, row["committed_event_id"])
    if event is None:
        raise DatabaseError("The confirmed draft's event is no longer available.", status_code=409)
    return {"draft_id": row["id"], "event": event}


def _commit_draft(
    conn: sqlite3.Connection, row: sqlite3.Row, draft: dict, source_key: str,
) -> dict:
    note = get_note(conn, row["note_id"]) if row["note_id"] is not None else None
    occurred_at = draft.get("occurred_at")
    if occurred_at is None:
        capture_timestamp = note["created_at"] if note else row["created_at"]
        captured = datetime.fromisoformat(capture_timestamp)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        # Workday filters use the local date, while capture metadata is stored in UTC.
        occurred_at = captured.astimezone()
    data = EventCreate.model_validate({
        **draft, "occurred_at": occurred_at, "source_key": source_key, "source_agent": "inbox",
    })
    event = events.create_event(conn, data)
    if event.get("source_conflict"):
        raise DatabaseError("The draft already has a different recorded event.", status_code=409)
    conn.execute(
        """UPDATE event_drafts
           SET status = 'confirmed', draft_json = ?, committed_event_id = ?, updated_at = ?
           WHERE id = ?""",
        (json.dumps(draft, ensure_ascii=False), event["id"], _now(), row["id"]),
    )
    _sync_note_status(conn, row["note_id"])
    return {"draft_id": row["id"], "event": event}


def confirm_draft(
    conn: sqlite3.Connection, draft_id: int, changes: EventDraftUpdate | None = None,
) -> dict:
    with write_transaction(conn):
        row = _get_draft(conn, draft_id)
        if row["status"] == "confirmed":
            return _confirmed_result(conn, row)
        if row["status"] != "pending":
            raise DatabaseError(f"Draft {draft_id} is already {row['status']}.", status_code=409)
        return _commit_draft(conn, row, _review_changes(row, changes), f"inbox:draft:{draft_id}")


def commit_note(
    conn: sqlite3.Connection, note_id: int, changes: EventDraftUpdate | None = None,
) -> dict:
    """Add an inbox note as an event without involving the agent."""
    source_key = f"inbox:note:{note_id}"
    with write_transaction(conn):
        note = _require_note(conn, note_id)
        prior = conn.execute(
            """SELECT event_drafts.* FROM event_drafts
               JOIN work_events ON work_events.id = event_drafts.committed_event_id
               WHERE event_drafts.note_id = ? AND work_events.source_key = ?""",
            (note_id, source_key),
        ).fetchone()
        if prior:
            return _confirmed_result(conn, prior)
        _require_raw_note(note)

        summary = next((line.strip() for line in note["raw_text"].splitlines() if line.strip()), "")
        payload = {"event_type": "manual", "summary": summary, "detail": note["raw_text"]}
        if changes is not None:
            payload.update(changes.model_dump(exclude_unset=True))
        draft = _reviewed_draft(payload)
        row = _insert_draft(conn, note_id, draft)
        return _commit_draft(conn, row, draft, source_key)


def discard_draft(conn: sqlite3.Connection, draft_id: int) -> bool:
    with write_transaction(conn):
        row = _get_draft(conn, draft_id)
        if row["status"] == "confirmed":
            raise DatabaseError(f"Draft {draft_id} has already been confirmed.", status_code=409)
        if row["status"] == "pending":
            conn.execute(
                "UPDATE event_drafts SET status = 'discarded', updated_at = ? WHERE id = ?",
                (_now(), draft_id),
            )
            _sync_note_status(conn, row["note_id"])
        return True


def discard_note(conn: sqlite3.Connection, note_id: int) -> bool:
    with write_transaction(conn):
        note = _require_note(conn, note_id)
        if note["status"] == "discarded":
            return True
        confirmed = conn.execute(
            "SELECT 1 FROM event_drafts WHERE note_id = ? AND status = 'confirmed' LIMIT 1",
            (note_id,),
        ).fetchone()
        if note["status"] == "committed" or confirmed:
            raise DatabaseError(f"Note {note_id} already has confirmed work. Discard each remaining draft.", status_code=409)

        now = _now()
        conn.execute(
            "UPDATE event_drafts SET status = 'discarded', updated_at = ? WHERE note_id = ? AND status = 'pending'",
            (now, note_id),
        )
        conn.execute("UPDATE inbox_notes SET status = 'discarded', updated_at = ? WHERE id = ?", (now, note_id))
        return True
