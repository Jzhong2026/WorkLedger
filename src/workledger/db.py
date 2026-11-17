"""SQLite connection management and migration runner."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_local = threading.local()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, db_path: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.db_path = db_path


def get_connection(db_path: Path) -> sqlite3.Connection:
    key = str(db_path)
    conn = getattr(_local, key, None)
    if conn is not None:
        return conn
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "locked" in msg or "busy" in msg:
            raise DatabaseError(
                f"Database temporarily locked: {db_path}. Retry shortly.",
                retryable=True,
                db_path=str(db_path),
            ) from e
        raise DatabaseError(
            f"Cannot open database: {db_path}. Check permissions or restore from backup.",
            db_path=str(db_path),
        ) from e
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    setattr(_local, key, conn)
    return conn


def close_connection(db_path: Path) -> None:
    key = str(db_path)
    conn = getattr(_local, key, None)
    if conn is not None:
        conn.close()
        delattr(_local, key)


def run_migrations(db_path: Path) -> int:
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    current = row["v"]

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied = 0
    for f in migration_files:
        version = int(f.stem.split("_")[0])
        if version <= current:
            continue
        sql = f.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
            applied += 1
        except sqlite3.Error as e:
            conn.rollback()
            raise DatabaseError(
                f"Migration {f.name} failed on {db_path}: {e}. "
                "Existing data preserved. Fix the issue or restore from backup.",
                db_path=str(db_path),
            ) from e
    return applied


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_migrations(db_path)
    return get_connection(db_path)