"""Explicit backup and restore for the SQLite database."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from .db import DatabaseError, close_connection


def backup_db(db_path: Path, dest: str) -> Path:
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        raise DatabaseError(f"Database not found: {db_path}", db_path=str(db_path))
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return dest_path


def restore_db(db_path: Path, src: str) -> None:
    src_path = Path(src)
    if not src_path.exists():
        raise DatabaseError(f"Backup file not found: {src_path}")
    try:
        test_conn = sqlite3.connect(str(src_path))
        test_conn.execute("SELECT count(*) FROM sqlite_master")
        test_conn.close()
    except sqlite3.Error as e:
        raise DatabaseError(f"Backup file is not a valid SQLite database: {e}") from e

    close_connection(db_path)
    if db_path.exists():
        safety = db_path.with_suffix(".db.pre-restore")
        shutil.copy2(db_path, safety)
    shutil.copy2(src_path, db_path)