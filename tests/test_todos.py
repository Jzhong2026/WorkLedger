"""Tests for #501: todos and follow-ups."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workledger.db import DatabaseError
from workledger.schemas import EventCreate, TodoCreate, TodoUpdate
from workledger.services.events import create_event
from workledger.services.todos import (
    create_todo,
    delete_todo,
    get_todo,
    list_todos,
    today_todos,
    update_todo,
)


class TestTodoCRUD:
    def test_create_and_get(self, conn):
        t = create_todo(conn, TodoCreate(title="Wait for reviewer", status="waiting", wait_target="Alice"))
        assert t["id"] > 0
        assert t["status"] == "waiting"
        fetched = get_todo(conn, t["id"])
        assert fetched["title"] == "Wait for reviewer"

    def test_complete_and_reopen(self, conn):
        t = create_todo(conn, TodoCreate(title="Fix bug"))
        done = update_todo(conn, t["id"], TodoUpdate(status="done"))
        assert done["status"] == "done"
        assert done["completed_at"] is not None
        reopened = update_todo(conn, t["id"], TodoUpdate(status="pending"))
        assert reopened["status"] == "pending"
        assert reopened["completed_at"] is None

    def test_delete(self, conn):
        t = create_todo(conn, TodoCreate(title="Temp"))
        assert delete_todo(conn, t["id"])
        assert get_todo(conn, t["id"]) is None

    def test_dedup_by_source_key(self, conn):
        t1 = create_todo(conn, TodoCreate(title="Follow up PR", source_key="todo:pr:42"))
        t2 = create_todo(conn, TodoCreate(title="Follow up PR", source_key="todo:pr:42"))
        assert t1["id"] == t2["id"]

    def test_link_to_event(self, conn):
        ev = create_event(conn, EventCreate(
            event_type="review_finding",
            occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            repo="org/repo", pr_number=10, summary="Finding",
        ))
        t = create_todo(conn, TodoCreate(title="Address finding", event_id=ev["id"]))
        assert t["event_id"] == ev["id"]

    def test_link_invalid_event_fails(self, conn):
        with pytest.raises(DatabaseError, match="not found"):
            create_todo(conn, TodoCreate(title="Bad link", event_id=9999))


class TestTodayPage:
    def test_due_today_shows(self, conn):
        create_todo(conn, TodoCreate(title="Due today", due_date="2026-11-17"))
        create_todo(conn, TodoCreate(title="Due later", due_date="2026-12-01"))
        items = today_todos(conn, "2026-11-17")
        titles = [t["title"] for t in items]
        assert "Due today" in titles
        assert "Due later" not in titles

    def test_no_date_not_overdue(self, conn):
        create_todo(conn, TodoCreate(title="No date"))
        items = today_todos(conn, "2026-11-17")
        assert any(t["title"] == "No date" for t in items)

    def test_done_excluded(self, conn):
        t = create_todo(conn, TodoCreate(title="Done task", due_date="2026-11-17"))
        update_todo(conn, t["id"], TodoUpdate(status="done"))
        items = today_todos(conn, "2026-11-17")
        assert not any(t["title"] == "Done task" for t in items)

    def test_followup_today_shows(self, conn):
        create_todo(conn, TodoCreate(title="Follow up", next_followup="2026-11-17"))
        items = today_todos(conn, "2026-11-17")
        assert any(t["title"] == "Follow up" for t in items)