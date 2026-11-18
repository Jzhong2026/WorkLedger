"""Tests for #497: SQLite foundation, dedup, transactions."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from workledger.db import close_connection, get_connection, init_db
from workledger.schemas import EventCreate, EventUpdate
from workledger.services.events import (
    create_event,
    get_pr_timeline,
    search_events,
    update_event,
)


def _ev(**kw) -> EventCreate:
    defaults = {
        "event_type": "review_finding",
        "occurred_at": datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        "repo": "org/repo",
        "pr_number": 42,
        "comment_id": "c1",
        "summary": "Found null check missing",
    }
    defaults.update(kw)
    return EventCreate(**defaults)


class TestInitAndPersistence:
    def test_empty_dir_creates_db(self, tmp_path):
        path = tmp_path / "sub" / "new.db"
        init_db(path)
        assert path.exists()
        conn = get_connection(path)
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        assert row["v"] >= 1
        close_connection(path)

    def test_restart_preserves_data(self, db_path):
        conn = get_connection(db_path)
        create_event(conn, _ev())
        close_connection(db_path)
        conn2 = init_db(db_path)
        items, total = search_events(conn2)
        assert total == 1
        assert items[0]["summary"] == "Found null check missing"


class TestDedup:
    def test_same_source_returns_same_record(self, conn):
        e1 = create_event(conn, _ev())
        e2 = create_event(conn, _ev())
        assert e1["id"] == e2["id"]
        _, total = search_events(conn)
        assert total == 1

    def test_different_actions_same_comment_independent(self, conn):
        review = create_event(conn, _ev(event_type="review_finding"))
        fix = create_event(conn, _ev(event_type="fix", summary="Applied null check"))
        reply = create_event(conn, _ev(event_type="reply_published", summary="Replied", reply_status="published"))
        assert len({review["id"], fix["id"], reply["id"]}) == 3
        timeline = get_pr_timeline(conn, "org/repo", 42)
        assert len(timeline) == 3

    def test_explicit_source_key_dedup(self, conn):
        e1 = create_event(conn, _ev(source_key="custom:abc"))
        e2 = create_event(conn, _ev(source_key="custom:abc", summary="Different summary"))
        assert e1["id"] == e2["id"]
        assert e2["summary"] == "Found null check missing"
        assert e2["source_conflict"] is True

    def test_distinct_fixes_within_one_pr_are_both_recorded(self, conn):
        first = _ev(event_type="fix", comment_id=None, summary="Fix A")
        second = first.model_copy(update={"summary": "Fix B"})
        first_record = create_event(conn, first)
        second_record = create_event(conn, second)
        assert first_record["id"] != second_record["id"]
        assert create_event(conn, second)["id"] == second_record["id"]

    def test_legacy_source_key_is_reused_for_the_same_payload(self, conn):
        with conn:
            conn.execute(
                """INSERT INTO work_events
                   (event_type, occurred_at, repo, pr_number, comment_id, source_key, summary)
                   VALUES ('review_finding', '2026-06-15 10:00:00', 'org/repo', 42,
                           'c1', 'review_finding:org/repo:42:c1', 'Found null check missing')"""
            )
        assert create_event(conn, _ev())["id"] == 1
        assert create_event(conn, _ev(summary="A distinct finding"))["id"] != 1

    def test_retry_after_event_edit_does_not_signal_source_conflict(self, conn):
        request = _ev(source_key="original-payload")
        record = create_event(conn, request)
        update_event(conn, record["id"], EventUpdate(summary="My edited version"))
        replay = create_event(conn, request)
        assert not replay.get("source_conflict", False)
        assert replay["summary"] == "My edited version"

    def test_concurrent_same_source(self, db_path):
        def worker(_):
            try:
                row = create_event(get_connection(db_path), _ev(source_key="concurrent:test"))
                return row["id"]
            finally:
                close_connection(db_path)

        with ThreadPoolExecutor(max_workers=5) as workers:
            results = list(workers.map(worker, range(5)))
        assert len(set(results)) == 1


class TestPartialFields:
    def test_update_can_clear_nullable_fields_without_overwriting_omitted_fields(self, conn):
        ev = create_event(conn, _ev(evidence_url="https://example.com/pr", root_cause="Typo"))
        saved = update_event(conn, ev["id"], EventUpdate(evidence_url=None, root_cause=None))
        assert saved["evidence_url"] is None
        assert saved["root_cause"] is None
        assert saved["summary"] == ev["summary"]

    def test_missing_optional_fields(self, conn):
        ev = create_event(conn, EventCreate(
            event_type="manual",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            summary="No jira, no link",
        ))
        assert ev["jira_key"] is None
        assert ev["evidence_url"] is None
        assert ev["repo"] is None

    def test_invalid_event_type_rejected(self, conn):
        with pytest.raises(ValidationError):
            EventCreate(event_type="invalid_type", occurred_at=datetime.now(UTC))


class TestTransactionRollback:
    def test_failed_write_no_partial_data(self, conn):
        create_event(conn, _ev(source_key="before:failure"))
        _, total_before = search_events(conn)
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute(
                "INSERT INTO work_events (event_type, occurred_at, source_key) VALUES (?, ?, ?)",
                ("manual", "2026-01-01", "before:failure"),
            )
        _, total_after = search_events(conn)
        assert total_after == total_before
