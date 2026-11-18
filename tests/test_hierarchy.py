"""Tests for Story-Task hierarchy."""
from __future__ import annotations

from datetime import datetime, timezone

from workledger.schemas import EventCreate
from workledger.services import events


def _ev(conn, summary, key, parent_id=None):
    ev = events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        summary=summary, jira_key=key, source_key=f"jira:{key}",
    ))
    if parent_id:
        conn.execute("UPDATE work_events SET parent_event_id=? WHERE id=?", (parent_id, ev["id"]))
        conn.commit()
    return ev


class TestHierarchy:
    def test_children_linked(self, conn):
        parent = _ev(conn, "Parent story", "RW-100")
        c1 = _ev(conn, "Task 1", "RW-101", parent["id"])
        c2 = _ev(conn, "Task 2", "RW-102", parent["id"])
        children = events.get_children(conn, parent["id"])
        assert {c["id"] for c in children} == {c1["id"], c2["id"]}

    def test_parent_field_exposed(self, conn):
        parent = _ev(conn, "Parent", "RW-200")
        child = _ev(conn, "Child", "RW-201", parent["id"])
        fetched = events.get_event(conn, child["id"])
        assert fetched["parent_event_id"] == parent["id"]

    def test_no_children_empty(self, conn):
        ev = _ev(conn, "Standalone", "RW-300")
        assert events.get_children(conn, ev["id"]) == []

    def test_parent_delete_nulls_child(self, conn):
        parent = _ev(conn, "Parent", "RW-400")
        child = _ev(conn, "Child", "RW-401", parent["id"])
        conn.execute("DELETE FROM work_events WHERE id=?", (parent["id"],))
        conn.commit()
        assert events.get_event(conn, child["id"])["parent_event_id"] is None