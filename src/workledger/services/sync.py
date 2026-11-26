"""Sync orchestration with per-source mutual exclusion."""
from __future__ import annotations

import sqlite3
import threading

from . import sync_bitbucket, sync_jira

_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


def _lock(source: str) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(source, threading.Lock())


def run_locked(source: str, fn, conn: sqlite3.Connection) -> dict:
    lock = _lock(source)
    if not lock.acquire(blocking=False):
        return {"source": source, "ok": False, "error": "sync in progress", "busy": True}
    try:
        return fn(conn)
    finally:
        lock.release()


def sync_all(conn: sqlite3.Connection) -> dict:
    jira = run_locked("jira", sync_jira.sync_jira, conn)
    bitbucket = run_locked("bitbucket", sync_bitbucket.sync_bitbucket, conn)
    return {"ok": bool(jira.get("ok")) and bool(bitbucket.get("ok")), "jira": jira, "bitbucket": bitbucket}
