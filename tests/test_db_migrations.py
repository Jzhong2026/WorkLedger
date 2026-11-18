"""Regression tests for migration rollback and simultaneous startup."""

from concurrent.futures import ThreadPoolExecutor
from shutil import copyfile
from threading import Barrier

import pytest

from workledger import db
from workledger.services import events, inbox


def test_failed_migration_is_rolled_back_and_can_be_retried(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations)
    path = tmp_path / "test.db"
    migration = migrations / "001_demo.sql"
    migration.write_text("CREATE TABLE demo (id INTEGER); INSERT INTO missing VALUES (7);", encoding="utf-8")
    try:
        with pytest.raises(db.DatabaseError, match="001_demo"):
            db.run_migrations(path)
        conn = db.get_connection(path)
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'demo'").fetchone() is None
        migration.write_text("CREATE TABLE demo (id INTEGER); INSERT INTO demo VALUES (7);", encoding="utf-8")
        assert db.run_migrations(path) == 1
        assert conn.execute("SELECT id FROM demo").fetchone()["id"] == 7
    finally:
        db.close_connection(path)


def test_migrations_capable_of_concurrent_startup(tmp_path):
    path = tmp_path / "concurrent.db"
    start = Barrier(6)

    def initialize():
        start.wait(timeout=10)
        try:
            return db.run_migrations(path)
        finally:
            db.close_connection(path)

    with ThreadPoolExecutor(max_workers=6) as workers:
        counts = list(workers.map(lambda _: initialize(), range(6)))
    try:
        conn = db.get_connection(path)
        assert sum(counts) == conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM work_events").fetchone()[0] == 0
    finally:
        db.close_connection(path)


def test_capture_migration_recovers_legacy_notes_and_keeps_saved_evidence(tmp_path, monkeypatch):
    legacy_migrations = tmp_path / "legacy"
    legacy_migrations.mkdir()
    for migration in sorted(db.MIGRATIONS_DIR.glob("*.sql"))[:5]:
        copyfile(migration, legacy_migrations / migration.name)
    path = tmp_path / "legacy.db"
    try:
        with monkeypatch.context() as original:
            original.setattr(db, "MIGRATIONS_DIR", legacy_migrations)
            conn = db.init_db(path)
        with conn:
            conn.execute(
                "INSERT INTO inbox_notes (raw_text, status) VALUES ('Please recover me', 'structured')"
            )
            conn.execute(
                """INSERT INTO work_events
                   (event_type, occurred_at, source_key, evidence_snapshot, snapshot_status, snapshot_at)
                   VALUES ('manual', '2026-06-01', 'old', 'saved evidence', 'captured', '2026-06-02')"""
            )
        assert db.run_migrations(path) >= 1
        assert inbox.get_note(conn, 1)["status"] == "raw"
        event = events.get_event(conn, 1)
        assert event["evidence_snapshot"] == "saved evidence"
        assert event["snapshot_attempt_at"] == event["snapshot_at"] == "2026-06-02"
        assert event["snapshot_source_url"] is None
    finally:
        db.close_connection(path)
