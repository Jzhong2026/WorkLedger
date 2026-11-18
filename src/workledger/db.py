"""SQLite connection management and migration runner."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

_local = threading.local()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseError(Exception):
    def __init__(
        self, message: str, *, retryable: bool = False, db_path: str = "",
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.db_path = db_path
        self.status_code = status_code


def _is_busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", 0)
    return (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _enable_wal(conn: sqlite3.Connection) -> None:
    # A simultaneous first open can fail the journal mode change without waiting.
    deadline = monotonic() + 5
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            return
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc) or monotonic() >= deadline:
                raise
            sleep(0.025)


def get_connection(db_path: Path) -> sqlite3.Connection:
    key = str(db_path)
    conn = getattr(_local, key, None)
    if conn is not None:
        return conn
    conn = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        _enable_wal(conn)
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error as e:
        if conn is not None:
            conn.close()
        if _is_busy(e):
            raise DatabaseError(
                f"Database temporarily locked: {db_path}. Retry shortly.",
                retryable=True,
                db_path=str(db_path),
            ) from e
        raise DatabaseError(
            f"Cannot open database: {db_path}. Check permissions or restore from backup.",
            db_path=str(db_path),
        ) from e
    setattr(_local, key, conn)
    return conn


def close_connection(db_path: Path) -> None:
    key = str(db_path)
    conn = getattr(_local, key, None)
    if conn is not None:
        conn.close()
        delattr(_local, key)


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Start a serialized write or participate in an existing write via a savepoint."""
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                yield
            return

        conn.execute("SAVEPOINT workledger_write")
        try:
            yield
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK TO workledger_write")
                conn.execute("RELEASE workledger_write")
            raise
        else:
            conn.execute("RELEASE workledger_write")
    except sqlite3.OperationalError as exc:
        if _is_busy(exc):
            raise DatabaseError("Database temporarily locked. Retry shortly.", retryable=True) from exc
        raise


def _execute_migration(conn: sqlite3.Connection, sql: str) -> None:
    # executescript commits an active transaction. Complete_statement recognizes
    # trigger bodies and quoted semicolons while retaining the caller's transaction.
    start = 0
    for index, char in enumerate(sql, 1):
        if char == ";" and sqlite3.complete_statement(sql[start:index]):
            conn.execute(sql[start:index])
            start = index
    if sql[start:].strip():
        conn.execute(sql[start:])


def run_migrations(db_path: Path) -> int:
    conn = get_connection(db_path)
    version_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if not version_table:
        with write_transaction(conn):
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "  version INTEGER PRIMARY KEY,"
                "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")"
            )

    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    applied = 0
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.stem.split("_")[0])
        if version <= current:
            continue
        try:
            with write_transaction(conn):
                current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
                if version <= current:
                    continue
                _execute_migration(conn, migration.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            current = version
            applied += 1
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError(
                f"Migration {migration.name} failed on {db_path}: {exc}. "
                "Fix the issue and retry or restore from backup.",
                db_path=str(db_path),
            ) from exc
    return applied


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_migrations(db_path)
    return get_connection(db_path)
