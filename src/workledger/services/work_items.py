"""Explicit active work items, historical context, and atomic handoffs."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from ..db import DatabaseError, write_transaction
from ..schemas import EventCreate, TodoCreate
from ..work_item_models import HandoffCreate, WorkItemCreate, WorkItemStage
from . import events, master_data, todos

_STATE_FIELDS = ("stage", "owner", "last_verified_result", "blocker", "next_step", "needs_decision", "followup_date")
_ITEM_COLUMNS = """
    w.*,
    (
        SELECT MIN(COALESCE(
            MIN(date(t.due_date), date(t.next_followup)), date(t.due_date), date(t.next_followup)
        ))
        FROM work_item_todos links
        JOIN todos t ON t.id = links.todo_id
        WHERE links.item_id = w.id AND t.status != 'done'
    ) AS linked_followup_date
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _item_payload(row: sqlite3.Row) -> dict:
    item = dict(row)
    item.pop("request_fingerprint", None)
    item["needs_decision"] = bool(item["needs_decision"])
    return item


def _handoff_payload(row: sqlite3.Row) -> dict:
    handoff = _item_payload(row)
    handoff["linked_event_ids"] = json.loads(row["linked_event_ids"])
    handoff["linked_todo_ids"] = json.loads(row["linked_todo_ids"])
    return handoff


def _find_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(f"SELECT {_ITEM_COLUMNS} FROM work_items w WHERE w.id = ?", (item_id,)).fetchone()
    return _item_payload(row) if row else None


def _require_item(conn: sqlite3.Connection, item_id: int) -> dict:
    item = _find_item(conn, item_id)
    if item is None:
        raise DatabaseError(f"Work item {item_id} not found.", status_code=404)
    return item


def _link_event(conn: sqlite3.Connection, item_id: int, event_id: int, actor: str, now: str) -> None:
    conn.execute(
        """INSERT INTO work_item_events (item_id, event_id, actor, linked_at)
           VALUES (?, ?, ?, ?) ON CONFLICT (item_id, event_id) DO NOTHING""",
        (item_id, event_id, actor, now),
    )


def _link_todo(conn: sqlite3.Connection, item_id: int, todo_id: int, actor: str, now: str) -> None:
    conn.execute(
        """INSERT INTO work_item_todos (item_id, todo_id, actor, linked_at)
           VALUES (?, ?, ?, ?) ON CONFLICT (item_id, todo_id) DO NOTHING""",
        (item_id, todo_id, actor, now),
    )


def create_work_item(conn: sqlite3.Connection, data: WorkItemCreate) -> dict:
    fingerprint = _fingerprint(data.model_dump(mode="json", exclude={"source_key"}))
    with write_transaction(conn):
        if data.source_key is not None:
            replay = conn.execute(
                "SELECT id, request_fingerprint FROM work_items WHERE source_key = ?", (data.source_key,),
            ).fetchone()
            if replay:
                if replay["request_fingerprint"] != fingerprint:
                    raise DatabaseError("This source key already identifies a different work-item request.", status_code=409)
                return _require_item(conn, replay["id"])

        source = None
        if data.source_event_id is not None:
            source = events.get_event(conn, data.source_event_id)
            if source is None:
                raise DatabaseError(f"Source event {data.source_event_id} not found.", status_code=404)
        project_id = data.project_id if data.project_id is not None else (source or {}).get("project_id")
        jira_key = data.jira_key or (source or {}).get("jira_key")
        if project_id is not None and not master_data.get_project(conn, project_id):
            raise DatabaseError(f"Project {project_id} not found.", status_code=404)

        now = _now()
        fields = data.model_dump(mode="json", include=set(_STATE_FIELDS))
        cursor = conn.execute(
            """INSERT INTO work_items (
                   title, goal, project_id, jira_key, source_event_id, stage, owner, last_verified_result,
                   blocker, next_step, needs_decision, followup_date, version, source_key, request_fingerprint,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (
                data.title, data.goal or None, project_id, jira_key, data.source_event_id,
                *(fields[field] for field in _STATE_FIELDS), data.source_key, fingerprint, now, now,
            ),
        )
        item_id = cursor.lastrowid
        if data.source_event_id is not None:
            _link_event(conn, item_id, data.source_event_id, data.actor, now)
        return _require_item(conn, item_id)


def list_work_items(
    conn: sqlite3.Connection, *, project_id: int | None = None, jira_key: str | None = None,
    stage: WorkItemStage | None = None, open_only: bool = False, page: int = 1, page_size: int = 20,
) -> tuple[list[dict], int]:
    filters = []
    params = []
    if project_id is not None:
        filters.append("w.project_id = ?")
        params.append(project_id)
    if jira_key and jira_key.strip():
        filters.append("w.jira_key = ?")
        params.append(jira_key.strip())
    if stage is not None:
        filters.append("w.stage = ?")
        params.append(stage)
    if open_only:
        filters.append("w.stage != 'done'")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    total = conn.execute(f"SELECT COUNT(*) FROM work_items w {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT {_ITEM_COLUMNS} FROM work_items w {where}
            ORDER BY w.updated_at DESC, w.id DESC LIMIT ? OFFSET ?""",
        (*params, page_size, (page - 1) * page_size),
    ).fetchall()
    return [_item_payload(row) for row in rows], total


def discover_events(
    conn: sqlite3.Connection, *, project_id: int | None = None, jira_key: str | None = None,
    page: int = 1, page_size: int = 20,
) -> tuple[list[dict], int]:
    """Return historical records as events, including records with no work item."""
    return events.search_events(
        conn, project_id=project_id, jira_key=jira_key.strip() if jira_key else None, page=page, page_size=page_size,
    )


def _context(conn: sqlite3.Connection, item: dict) -> dict:
    from .learning import recall_lessons

    item_id = item["id"]
    event_links = conn.execute(
        """SELECT links.event_id, links.actor, links.linked_at
           FROM work_item_events links
           JOIN work_events e ON e.id = links.event_id
           WHERE links.item_id = ? ORDER BY e.occurred_at DESC, e.id DESC""",
        (item_id,),
    ).fetchall()
    related_events = []
    for link in event_links:
        event = events.get_event(conn, link["event_id"])
        related_events.append({**event, "linked_by": link["actor"], "linked_at": link["linked_at"]})
    todo_rows = conn.execute(
        """SELECT t.*, links.actor AS linked_by, links.linked_at
           FROM work_item_todos links JOIN todos t ON t.id = links.todo_id
           WHERE links.item_id = ?
           ORDER BY t.status = 'done', COALESCE(t.next_followup, t.due_date, '9999'), t.id""",
        (item_id,),
    ).fetchall()
    history = conn.execute(
        "SELECT * FROM work_item_handoffs WHERE item_id = ? ORDER BY version DESC", (item_id,),
    ).fetchall()
    source_id = item["source_event_id"]
    source = events.get_event(conn, source_id) if source_id is not None else None
    parent_id = source["parent_event_id"] if source else None
    query = " ".join(part for part in (item["title"], item["goal"]) if part)
    lessons_error = None
    try:
        related_lessons = recall_lessons(
            conn, query, project_id=item["project_id"], limit=5, exclude_source_work_item_id=item_id,
        )
    except (DatabaseError, sqlite3.Error):
        related_lessons = []
        lessons_error = "Related lessons could not be loaded. Refresh this item to retry."
    return {
        "item": item,
        "events": related_events,
        "todos": [dict(row) for row in todo_rows],
        "history": [_handoff_payload(row) for row in history],
        "source_event": source,
        "parent_event": events.get_event(conn, parent_id) if parent_id is not None else None,
        "child_events": events.get_children(conn, source_id) if source_id is not None else [],
        "related_lessons": related_lessons,
        "related_lessons_error": lessons_error,
    }


def get_work_item_context(conn: sqlite3.Connection, item_id: int) -> dict | None:
    """Read a coherent context even if another writer records a handoff concurrently."""
    if conn.in_transaction:
        item = _find_item(conn, item_id)
        return _context(conn, item) if item is not None else None
    conn.execute("BEGIN")
    with conn:
        return get_work_item_context(conn, item_id)


def _check_link_targets(conn: sqlite3.Connection, data: HandoffCreate) -> None:
    for event_id in data.event_ids:
        if events.get_event(conn, event_id) is None:
            raise DatabaseError(f"Event {event_id} could not be linked because it no longer exists.", status_code=404)
    for todo_id in data.todo_ids:
        if todos.get_todo(conn, todo_id) is None:
            raise DatabaseError(f"To-do {todo_id} could not be linked because it no longer exists.", status_code=404)


def _record_event(
    conn: sqlite3.Connection, item: dict, data: HandoffCreate, changes: dict, version: int,
) -> dict:
    verified_result = changes.get("last_verified_result")
    event = events.create_event(conn, EventCreate(
        event_type="verification" if verified_result else "manual",
        occurred_at=datetime.now().astimezone(),
        jira_key=item["jira_key"], source_key=f"work-item:{item['id']}:handoff:{version}",
        source_agent=data.actor, summary=data.summary,
        detail=f"Work item: {item['title']}\nStage: {item['stage']} → {changes.get('stage', item['stage'])}",
        verification_result=verified_result, verification_done=bool(verified_result),
    ))
    if event.get("source_conflict"):
        raise DatabaseError("A different work event already uses this handoff's source key.", status_code=409)
    if item["project_id"] is not None:
        conn.execute("UPDATE work_events SET project_id = ? WHERE id = ?", (item["project_id"], event["id"]))
    return event


def record_handoff(conn: sqlite3.Connection, item_id: int, data: HandoffCreate) -> dict:
    changes = data.model_dump(mode="json", include=set(_STATE_FIELDS), exclude_unset=True)
    immutable = data.model_dump(mode="json", exclude={"source_key", *_STATE_FIELDS})
    fingerprint = _fingerprint({**immutable, **changes})
    with write_transaction(conn):
        item = _require_item(conn, item_id)
        if data.source_key is not None:
            replay = conn.execute(
                "SELECT * FROM work_item_handoffs WHERE item_id = ? AND source_key = ?",
                (item_id, data.source_key),
            ).fetchone()
            if replay:
                if replay["request_fingerprint"] != fingerprint:
                    raise DatabaseError("This source key already identifies a different handoff request.", status_code=409)
                return {**_context(conn, item), "handoff": _handoff_payload(replay), "replayed": True}

        if item["version"] != data.expected_version:
            raise DatabaseError(
                f"Work item version changed from {data.expected_version} to {item['version']}. "
                "Reload the item and review the latest updates before retrying.", status_code=409,
            )
        _check_link_targets(conn, data)

        now = _now()
        version = item["version"] + 1
        state = {**item, **changes}
        new_event = _record_event(conn, item, data, changes, version)
        _link_event(conn, item_id, new_event["id"], data.actor, now)
        for event_id in data.event_ids:
            _link_event(conn, item_id, event_id, data.actor, now)
        for todo_id in data.todo_ids:
            _link_todo(conn, item_id, todo_id, data.actor, now)

        new_todo_id = None
        if data.todo is not None:
            todo = todos.create_todo(conn, TodoCreate(event_id=new_event["id"], **data.todo.model_dump(mode="json")))
            new_todo_id = todo["id"]
            if item["project_id"] is not None:
                conn.execute("UPDATE todos SET project_id = ? WHERE id = ?", (item["project_id"], new_todo_id))
            _link_todo(conn, item_id, new_todo_id, data.actor, now)

        updated = conn.execute(
            """UPDATE work_items SET stage = ?, owner = ?, last_verified_result = ?, blocker = ?, next_step = ?,
                   needs_decision = ?, followup_date = ?, version = ?, updated_at = ?
               WHERE id = ? AND version = ?""",
            (*(state[field] for field in _STATE_FIELDS), version, now, item_id, data.expected_version),
        )
        if updated.rowcount != 1:
            raise DatabaseError("The work item version changed. Reload the item before retrying.", status_code=409)
        cursor = conn.execute(
            """INSERT INTO work_item_handoffs (
                   item_id, version, summary, event_id, todo_id, actor, previous_stage, stage, owner,
                   last_verified_result, blocker, next_step, needs_decision, followup_date, linked_event_ids,
                   linked_todo_ids, source_key, request_fingerprint, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, version, data.summary, new_event["id"], new_todo_id, data.actor, item["stage"],
                *(state[field] for field in _STATE_FIELDS), json.dumps(data.event_ids), json.dumps(data.todo_ids),
                data.source_key, fingerprint, now,
            ),
        )
        row = conn.execute("SELECT * FROM work_item_handoffs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return {**_context(conn, _require_item(conn, item_id)), "handoff": _handoff_payload(row), "replayed": False}
