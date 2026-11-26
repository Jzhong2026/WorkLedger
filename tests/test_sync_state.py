from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from workledger.services import sync_state


def test_migration_010_applies(conn):
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version >= 10
    conn.execute("SELECT source, last_attempt_at, last_success_at, last_error, detail_json FROM sync_state")


def test_success_roundtrip_and_error_clears(conn):
    sync_state.record_attempt(conn, "jira")
    sync_state.record_success(conn, "jira", {"created": 2, "my_account_id": "acc-1"})
    states = sync_state.get_states(conn)
    assert states["jira"]["last_success_at"] is not None
    assert states["jira"]["detail"] == {"created": 2, "my_account_id": "acc-1"}
    assert states["jira"]["last_error"] is None
    sync_state.record_error(conn, "jira", "twg exploded")
    states = sync_state.get_states(conn)
    assert states["jira"]["last_error"] == "twg exploded"
    assert states["jira"]["last_success_at"] is not None  # 失败不清空上次成功时间
    sync_state.record_success(conn, "jira", {})
    assert sync_state.get_states(conn)["jira"]["last_error"] is None


def test_is_stale_rules(conn):
    assert sync_state.is_stale(None, 15) is True
    assert sync_state.is_stale({"last_success_at": None}, 15) is True
    now = datetime.now(UTC)
    fresh = {"last_success_at": (now - timedelta(minutes=10)).isoformat()}
    old = {"last_success_at": (now - timedelta(minutes=61)).isoformat()}
    assert sync_state.is_stale(fresh, 15) is False
    assert sync_state.is_stale(old, 15) is True
    day_old = {"last_success_at": (now - timedelta(hours=25)).isoformat()}
    assert sync_state.is_stale(day_old, 0) is True
    assert sync_state.is_stale({"last_success_at": (now - timedelta(hours=2)).isoformat()}, 0) is False
