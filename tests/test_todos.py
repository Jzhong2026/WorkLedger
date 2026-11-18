"""Tests for #501: todos and follow-ups."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from workledger.db import DatabaseError
from workledger.schemas import EventCreate, TodoCreate, TodoUpdate
from workledger.services.events import create_event
from workledger.services.master_data import create_project
from workledger.services.todos import (
    create_todo,
    delete_todo,
    get_todo,
    list_todos,
    today_summary,
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

    def test_update_can_clear_followup_without_changing_due_date(self, conn):
        t = create_todo(conn, TodoCreate(title="Follow up", due_date="2026-11-17", next_followup="2026-11-16"))
        updated = update_todo(conn, t["id"], TodoUpdate(next_followup=None))
        assert updated["next_followup"] is None
        assert updated["due_date"] == "2026-11-17"

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
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
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

    def test_today_summary_groups_and_counts_all_tasks(self, conn):
        for number in range(102):
            create_todo(conn, TodoCreate(title=f"Future task {number}", due_date="2026-12-01"))
        create_todo(conn, TodoCreate(title="Overdue", next_followup="2026-11-16", due_date="2026-11-17"))
        waiting = create_todo(conn, TodoCreate(title="Today", due_date="2026-11-17", status="waiting"))
        create_todo(conn, TodoCreate(title="Unscheduled"))
        create_todo(conn, TodoCreate(title="Complete", status="done"))

        summary = today_summary(conn, "2026-11-17")
        assert summary["today"] == "2026-11-17"
        assert summary["counts"] == {"pending": 104, "waiting": 1, "done": 1}
        assert {
            group: [item["title"] for item in items]
            for group, items in summary["groups"].items()
        } == {"overdue": ["Overdue"], "today": ["Today"], "unscheduled": ["Unscheduled"]}

        update_todo(conn, waiting["id"], TodoUpdate(status="done"))
        summary = today_summary(conn, "2026-11-17")
        assert summary["counts"] == {"pending": 104, "waiting": 0, "done": 2}
        assert summary["groups"]["today"] == []


def test_list_todos_scopes_insight_drilldown_to_created_window_and_project(conn):
    date = "2026-11-17"
    project = create_project(conn, name="Infrastructure", key="infra")
    event = create_event(conn, EventCreate(
        event_type="manual",
        occurred_at=datetime(2026, 11, 17, tzinfo=UTC),
        summary="Follow up deployment",
    ))
    inherited = create_todo(conn, TodoCreate(title="Inherited project", event_id=event["id"], status="waiting"))
    direct = create_todo(conn, TodoCreate(title="Direct project", status="waiting"))
    unassigned = create_todo(conn, TodoCreate(title="Unassigned", status="waiting"))
    older = create_todo(conn, TodoCreate(title="Outside period", status="waiting"))
    with conn:
        conn.execute("UPDATE work_events SET project_id = ? WHERE id = ?", (project["id"], event["id"]))
        conn.execute("UPDATE todos SET project_id = ? WHERE id IN (?, ?)", (project["id"], direct["id"], older["id"]))
        conn.execute("UPDATE todos SET created_at = ? WHERE id != ?", (f"{date} 18:00:00", older["id"]))
        conn.execute("UPDATE todos SET created_at = '2026-10-01 12:00:00' WHERE id = ?", (older["id"],))

    scoped, count = list_todos(conn, status="waiting", project_id=project["id"], date_from=date, date_to=date)
    assert count == 2
    assert {todo["id"] for todo in scoped} == {inherited["id"], direct["id"]}
    unknown, count = list_todos(conn, project_id=0, date_from=date, date_to=date)
    assert count == 1
    assert unknown[0]["id"] == unassigned["id"]
