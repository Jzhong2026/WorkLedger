from __future__ import annotations

import json

import pytest

from workledger.config import settings
from workledger.services import jira_import, sync_jira, sync_state


def _issue(key, status="In Progress", category="indeterminate", assignee="acc-jason", updated="2026-11-24T20:33:40.416-0500"):
    return {
        "key": key, "summary": f"Summary {key}",
        "status": {"name": status, "statusCategory": {"key": category}},
        "assignee": {"accountId": assignee, "displayName": "JasonZhong"} if assignee else None,
        "created": "2026-11-01T09:00:00.000-0500", "updated": updated,
    }


def _runner(tmp_path, issues):
    calls = []

    def runner(args):
        calls.append(args)
        limit = args[args.index("--limit") + 1]
        # 模拟 twg 服务端过滤：currentUser() 探测（--limit 1）只返回 Jason 名下的票。
        shown = [i for i in issues if (i.get("assignee") or {}).get("accountId") == "acc-jason"] if limit == "1" else issues
        payload = tmp_path / f"twg-{len(calls)}.json"
        payload.write_text(json.dumps({"data": {"issues": shown}}), encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    return runner, calls


def test_sync_creates_snapshots_and_items_for_my_open_tickets(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-901"), _issue("AIP-902")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    assert result["created"] == 2
    assert result["items_created"] == 2
    assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 2
    stages = {r["jira_key"]: r["stage"] for r in conn.execute("SELECT jira_key, stage FROM work_items")}
    assert stages == {"RW-901": "active", "AIP-902": "active"}
    assert conn.execute("SELECT key FROM projects WHERE key='AIP'").fetchone() is not None
    state = sync_state.get_states(conn)["jira"]
    assert state["last_success_at"] is not None
    assert state["detail"]["my_account_id"] == "acc-jason"


def test_backlog_and_historical_done_get_no_items(conn, tmp_path):
    issues = [_issue("RW-903", "In Backlog", "new"), _issue("RW-904", "Done", "done")]
    runner, _ = _runner(tmp_path, issues)
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["created"] == 2
    assert result["items_created"] == 0


def test_done_transition_creates_done_item(conn, tmp_path):
    jira_import.import_issues(conn, [_issue("RW-905")], project_key="RW", project_name="RW")
    runner, _ = _runner(tmp_path, [_issue("RW-905", "Done", "done", updated="2026-11-25T20:33:40.416-0500")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["items_created"] == 1
    assert conn.execute("SELECT stage FROM work_items WHERE jira_key='RW-905'").fetchone()[0] == "done"


def test_acceptance_maps_to_verification(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-906", "Acceptance", "indeterminate")])
    sync_jira.sync_jira(conn, runner=runner)
    assert conn.execute("SELECT stage FROM work_items WHERE jira_key='RW-906'").fetchone()[0] == "verification"


def test_other_assignee_gets_snapshot_not_item(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-907", assignee="acc-joseph")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["created"] == 1
    assert result["items_created"] == 0


def test_rerun_idempotent_and_reassignment_keeps_item(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-908")])
    sync_jira.sync_jira(conn, runner=runner)
    runner2, _ = _runner(tmp_path, [_issue("RW-908", assignee=None)])
    result = sync_jira.sync_jira(conn, runner=runner2)
    assert result["items_created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM work_items WHERE jira_key='RW-908'").fetchone()[0] == 1


def test_jql_contains_exclude_window_and_imported_keys(conn, tmp_path):
    jira_import.import_issues(conn, [_issue("RW-909", "Done", "done")], project_key="RW", project_name="RW")
    runner, calls = _runner(tmp_path, [_issue("RW-910")])
    sync_jira.sync_jira(conn, runner=runner)
    main_jql = calls[0][calls[0].index("--jql") + 1]
    assert "project in (RW, AIP)" in main_jql
    assert "key not in (AIP-96)" in main_jql
    assert "updated >= -30d" in main_jql
    assert "RW-909" in main_jql
    assert "assignee = currentUser()" in main_jql


def test_failure_records_error(conn, tmp_path):
    def broken(args):
        raise ValueError("twg exploded")
    result = sync_jira.sync_jira(conn, runner=broken)
    assert result["ok"] is False
    assert "twg exploded" in sync_state.get_states(conn)["jira"]["last_error"]
