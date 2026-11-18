"""Tests for quick inbox: notes, drafts, confirm into events."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from workledger.db import DatabaseError, close_connection, get_connection
from workledger.schemas import EventDraftUpdate
from workledger.services import events, inbox


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

    def test_confirm_twice_returns_same_event(self, conn):
        n = inbox.create_note(conn, "x")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        first = inbox.confirm_draft(conn, drafts[0]["id"])
        assert inbox.confirm_draft(conn, drafts[0]["id"]) == first
        assert events.search_events(conn)[1] == 1

    def test_concurrent_confirm_returns_same_event(self, conn, db_path):
        note = inbox.create_note(conn, "Some note")
        draft = inbox.save_drafts(conn, note["id"], self._draft_events())[0]
        start = Barrier(3)

        def confirm(_):
            start.wait(timeout=10)
            try:
                return inbox.confirm_draft(get_connection(db_path), draft["id"])
            finally:
                close_connection(db_path)

        with ThreadPoolExecutor(max_workers=3) as workers:
            responses = list(workers.map(confirm, range(3)))
        assert len({response["event"]["id"] for response in responses}) == 1
        assert events.search_events(conn)[1] == 1

    def test_confirm_rolls_back_event_when_draft_update_fails(self, conn):
        n = inbox.create_note(conn, "a draft")
        draft = inbox.save_drafts(conn, n["id"], [{"event_type": "manual", "summary": "A"}])[0]
        conn.execute(
            """CREATE TRIGGER force_invalid_confirmation BEFORE UPDATE OF committed_event_id ON event_drafts
               BEGIN SELECT RAISE(ABORT, 'failed draft update'); END"""
        )
        with pytest.raises((DatabaseError, sqlite3.IntegrityError), match="failed draft update"):
            inbox.confirm_draft(conn, draft["id"])
        assert events.search_events(conn)[1] == 0
        assert inbox.list_drafts(conn, note_id=n["id"])[0]["status"] == "pending"
        conn.execute("DROP TRIGGER force_invalid_confirmation")
        inbox.confirm_draft(conn, draft["id"])
        assert events.search_events(conn)[1] == 1

    def test_discard_draft(self, conn):
        n = inbox.create_note(conn, "x")
        drafts = inbox.save_drafts(conn, n["id"], self._draft_events())
        assert inbox.discard_draft(conn, drafts[0]["id"])
        assert inbox.list_drafts(conn, status="pending") == []
        assert inbox.get_note(conn, n["id"])["status"] == "raw"

    def test_no_drafts_leaves_note_available_to_retry(self, conn):
        note = inbox.create_note(conn, "No draft returned")
        assert inbox.save_drafts(conn, note["id"], []) == []
        assert inbox.get_note(conn, note["id"])["status"] == "raw"

    def test_discard_note_retires_pending_drafts(self, conn):
        note = inbox.create_note(conn, "Pending drafts")
        draft = inbox.save_drafts(conn, note["id"], self._draft_events())[0]
        assert inbox.discard_note(conn, note["id"])
        assert inbox.list_drafts(conn, note_id=note["id"]) == []
        with pytest.raises(DatabaseError, match="discarded"):
            inbox.confirm_draft(conn, draft["id"])

    def test_edit_draft_and_confirm_with_final_changes(self, conn):
        note = inbox.create_note(conn, "Raw note")
        draft = inbox.save_drafts(conn, note["id"], self._draft_events())[0]
        edited = inbox.update_draft(conn, draft["id"], EventDraftUpdate(summary="Reviewed"))
        assert edited["draft"]["summary"] == "Reviewed"
        confirmed = inbox.confirm_draft(conn, draft["id"], EventDraftUpdate(detail="Confirmed detail"))
        assert confirmed["event"]["summary"] == "Reviewed"
        assert confirmed["event"]["detail"] == "Confirmed detail"

    def test_commit_note_offline_with_retry(self, conn):
        note = inbox.create_note(conn, "Raw note")
        changes = EventDraftUpdate(summary="Manual entry", root_cause="Known")
        result = inbox.commit_note(conn, note["id"], changes)
        event = result["event"]
        assert event["event_type"] == "manual"
        assert event["summary"] == "Manual entry"
        assert event["detail"] == "Raw note"
        assert event["root_cause"] == "Known"
        assert inbox.commit_note(conn, note["id"], changes) == result
        assert events.search_events(conn)[1] == 1

    def test_after_midnight_capture_defaults_to_local_occurrence_date(self, conn, monkeypatch):
        class ShanghaiDateTime(datetime):
            def astimezone(self, tz=None):
                return super().astimezone(tz or timezone(timedelta(hours=8)))

        monkeypatch.setattr(inbox, "datetime", ShanghaiDateTime)
        note = inbox.create_note(conn, "Captured just after midnight")
        with conn:
            conn.execute(
                "UPDATE inbox_notes SET created_at = ? WHERE id = ?",
                ("2026-06-14 16:30:00", note["id"]),
            )
        result = inbox.commit_note(conn, note["id"])
        assert result["event"]["occurred_at"] == "2026-06-15 00:30:00"

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
