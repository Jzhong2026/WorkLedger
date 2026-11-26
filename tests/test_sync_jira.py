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
    assert "assignee = currentUser()" in main_jql
    # scope 查询不得内联已导入 keys（数千 key 会撑爆 Windows argv）
    assert "key in (" not in main_jql
    later_jqls = [c[c.index("--jql") + 1] for c in calls[1:]]
    assert any("key in (RW-909)" in jql for jql in later_jqls)


def test_failure_records_error(conn, tmp_path):
    def broken(args):
        raise ValueError("twg exploded")
    result = sync_jira.sync_jira(conn, runner=broken)
    assert result["ok"] is False
    assert "twg exploded" in sync_state.get_states(conn)["jira"]["last_error"]


def test_pagination_follows_cursor_across_pages(conn, tmp_path):
    calls = []

    def runner(args):
        calls.append(args)
        limit = args[args.index("--limit") + 1]
        if limit == "1":  # identity probe: one page, no cursor
            page = {"data": {"issues": [_issue("RW-920")]}}
        elif "--after" in args:
            page = {"data": {"issues": [_issue("RW-922")]}}
        else:
            page = {"data": {"issues": [_issue("RW-920"), _issue("RW-921")]},
                    "pageInfo": {"hasNextPage": True, "nextCursor": "c1"}}
        payload = tmp_path / f"twg-page-{len(calls)}.json"
        payload.write_text(json.dumps(page), encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    assert result["created"] == 3
    assert result["issues"] == 3
    assert calls[0][calls[0].index("--limit") + 1] == "100"
    assert calls[1][calls[1].index("--after") + 1] == "c1"
    assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 3


def test_imported_key_refresh_chunks_bound_argv(conn, tmp_path):
    # 回归：3000 个已导入 key 不得内联进主 JQL（Windows argv 32767 上限 → WinError 206）。
    keys = [f"RW-{n}" for n in range(100000, 103000)]
    conn.executemany(
        "INSERT INTO work_events (event_type, occurred_at, source_key, source_agent, jira_key, summary, extra_json) "
        "VALUES ('manual', '2026-11-01 09:00:00', ?, 'jira-import', ?, ?, '{}')",
        [(f"jira:{k}", k, f"Summary {k}") for k in keys],
    )
    conn.commit()
    scope_issues = [_issue("RW-100000"), _issue("RW-9001"), _issue("RW-9002")]
    calls = []

    def runner(args):
        calls.append(args)
        jql = args[args.index("--jql") + 1]
        limit = args[args.index("--limit") + 1]
        if limit == "1":  # identity probe
            shown = [i for i in scope_issues if (i.get("assignee") or {}).get("accountId") == "acc-jason"]
        elif "key in (" in jql:  # refresh chunk：模拟服务端按 key 过滤
            clause = jql.split("key in (", 1)[1].split(")", 1)[0]
            chunk = [k.strip() for k in clause.split(",")]
            shown = [_issue(k) for k in chunk[:2]]
        else:
            shown = scope_issues
        payload = tmp_path / f"twg-argv-{len(calls)}.json"
        payload.write_text(json.dumps({"data": {"issues": shown}}), encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    # 每次 runner 调用的完整 argv 必须远低于 Windows 32767 上限
    assert all(len(" ".join(args)) < 30000 for args in calls)
    scope_jql = calls[0][calls[0].index("--jql") + 1]
    assert "key in (" not in scope_jql
    refresh_calls = [c for c in calls if "key in (" in c[c.index("--jql") + 1]]
    assert len(refresh_calls) == 6  # ceil(2999 / 500)
    refreshed = []
    for c in refresh_calls:
        clause = c[c.index("--jql") + 1].split("key in (", 1)[1].split(")", 1)[0]
        chunk = [k.strip() for k in clause.split(",")]
        assert len(chunk) <= 500
        refreshed.extend(chunk)
    assert len(refreshed) == 2999
    assert "RW-100000" not in refreshed  # scope 已覆盖的 key 不再刷新
    assert result["created"] == 2  # RW-9001 / RW-9002
    assert result["updated"] == 13  # RW-100000 + 每块 2 条 × 6 块
    assert result["issues"] == 15
    assert result["truncated"] is False


def test_top_level_array_payload_records_error_envelope(conn, tmp_path):
    def runner(args):
        payload = tmp_path / "twg-array.json"
        payload.write_text("[1, 2, 3]", encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is False
    state = sync_state.get_states(conn)["jira"]
    assert state["last_attempt_at"] is not None
    assert "get" in state["last_error"]  # AttributeError: 'list' object has no attribute 'get'
