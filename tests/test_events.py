"""Tests for #497: SQLite foundation, dedup, transactions."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workledger.db import DatabaseError, close_connection, get_connection, init_db
from workledger.schemas import EventCreate
from workledger.services.events import create_event, get_event, get_pr_timeline, search_events


def _ev(**kw) -> EventCreate:
    defaults = dict(
        event_type="review_finding",
        occurred_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
        repo="org/repo",
        pr_number=42,
        comment_id="c1",
        summary="Found null check missing",
    )
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

    def test_concurrent_same_source(self, db_path):
        import threading
        results = []
        errors = []

        def worker():
            try:
                c = get_connection(db_path)
                r = create_event(c, _ev(source_key="concurrent:test"))
                results.append(r["id"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert len(set(results)) == 1


class TestPartialFields:
    def test_missing_optional_fields(self, conn):
        ev = create_event(conn, EventCreate(
            event_type="manual",
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="No jira, no link",
        ))
        assert ev["jira_key"] is None
        assert ev["evidence_url"] is None
        assert ev["repo"] is None

    def test_invalid_event_type_rejected(self, conn):
        with pytest.raises(Exception):
            EventCreate(event_type="invalid_type", occurred_at=datetime.now(timezone.utc))


class TestTransactionRollback:
    def test_failed_write_no_partial_data(self, conn):
        create_event(conn, _ev(source_key="before:failure"))
        _, total_before = search_events(conn)
        try:
            conn.execute("INSERT INTO work_events (event_type, occurred_at, source_key) VALUES ('manual', '2026-01-01', 'before:failure')")
            conn.commit()
        except Exception:
            conn.rollback()
        _, total_after = search_events(conn)
        assert total_after == total_before