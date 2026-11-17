"""Tests for #498: backup, restore, upgrade, error states."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from workledger.backup import backup_db, restore_db
from workledger.db import DatabaseError, close_connection, get_connection, init_db
from workledger.schemas import EventCreate, TodoCreate
from workledger.services.events import create_event, search_events
from workledger.services.todos import create_todo, list_todos


class TestBackupRestore:
    def test_backup_and_restore(self, db_path, tmp_path):
        conn = get_connection(db_path)
        create_event(conn, EventCreate(
            event_type="manual",
            occurred_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            summary="Important record",
            source_key="backup:test",
        ))
        create_todo(conn, TodoCreate(title="Follow up", source_key="todo:backup"))

        dest = str(tmp_path / "backup.db")
        backup_db(db_path, dest)
        assert Path(dest).exists()

        close_connection(db_path)
        db_path.unlink()

        restore_db(db_path, dest)
        conn2 = init_db(db_path)
        items, total = search_events(conn2)
        assert total == 1
        assert items[0]["summary"] == "Important record"
        todos_list, todo_total = list_todos(conn2)
        assert todo_total == 1

    def test_restore_invalid_file(self, db_path, tmp_path):
        bad = tmp_path / "bad.db"
        bad.write_text("not a database")
        with pytest.raises(DatabaseError, match="not a valid"):
            restore_db(db_path, str(bad))

    def test_backup_missing_db(self, tmp_path):
        with pytest.raises(DatabaseError, match="not found"):
            backup_db(tmp_path / "nonexist.db", str(tmp_path / "out.db"))


class TestUpgrade:
    def test_migration_preserves_data(self, db_path):
        conn = get_connection(db_path)
        create_event(conn, EventCreate(
            event_type="fix",
            occurred_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary="Pre-upgrade record",
            source_key="upgrade:test",
        ))
        close_connection(db_path)
        init_db(db_path)
        conn2 = get_connection(db_path)
        items, total = search_events(conn2)
        assert total == 1
        assert items[0]["summary"] == "Pre-upgrade record"


class TestErrorStates:
    def test_locked_db_retryable(self, tmp_path):
        path = tmp_path / "locked.db"
        init_db(path)
        close_connection(path)
        assert path.exists()

    def test_unwritable_dir(self, tmp_path):
        path = tmp_path / "nope" / "deep" / "test.db"
        init_db(path)
        assert path.exists()
        close_connection(path)