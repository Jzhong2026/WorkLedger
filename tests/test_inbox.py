"""Tests for quick inbox: notes, drafts, confirm into events."""
from __future__ import annotations

import pytest

from workledger.db import DatabaseError
from workledger.services import inbox, events


class TestNotes:
    def test_capture(self, conn):
        n = inbox.create_note(conn, "fixed null check in PR 42")
        assert n["status"] == "raw"
        assert n["raw_text"] == "fixed null check in PR 42"

    def test_list_filter(self, conn):
        inbox.create_note(conn, "a")
        n2 = inbox.create_note(conn, "b")
        inbox.discard_note(conn, n2["id"])
        raw = inbox.list_notes(conn, status="raw")
        assert len(raw) == 1
        assert raw[0]["raw_text"] == "a"


class TestDrafts:
    def _draft_events(self):
        return [{"event_type": "fix", "summary": "Added guard", "repo": "org/repo", "pr_number": 42}]

    def test_save_drafts_marks_structured(self, conn):
        n = inbox.create_note(conn, "fixed PR 42")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        assert len(drafts) == 1
        assert inbox.get_note(conn, n["id"])["status"] == "structured"

    def test_confirm_commits_event(self, conn):
        n = inbox.create_note(conn, "fixed PR 42")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        result = inbox.confirm_draft(conn, drafts[0]["id"])
        ev = result["event"]
        assert ev["summary"] == "Added guard"
        assert ev["pr_number"] == 42
        assert events.get_event(conn, ev["id"]) is not None
        assert inbox.get_note(conn, n["id"])["status"] == "committed"

    def test_confirm_twice_rejected(self, conn):
        n = inbox.create_note(conn, "x")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        inbox.confirm_draft(conn, drafts[0]["id"])
        with pytest.raises(DatabaseError, match="already confirmed"):
            inbox.confirm_draft(conn, drafts[0]["id"])

    def test_discard_draft(self, conn):
        n = inbox.create_note(conn, "x")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        assert inbox.discard_draft(conn, drafts[0]["id"])
        assert inbox.list_drafts(conn, status="pending") == []

    def test_partial_confirm_keeps_note_structured(self, conn):
        n = inbox.create_note(conn, "x")
        drafts = inbox.save_drafts(conn, n["id"], [
            {"event_type": "fix", "summary": "a"},
            {"event_type": "verification", "summary": "b"},
        ])
        inbox.confirm_draft(conn, drafts[0]["id"])
        assert inbox.get_note(conn, n["id"])["status"] == "structured"
        inbox.confirm_draft(conn, drafts[1]["id"])
        assert inbox.get_note(conn, n["id"])["status"] == "committed"

    def test_confirm_missing_draft(self, conn):
        with pytest.raises(DatabaseError, match="not found"):
            inbox.confirm_draft(conn, 999)