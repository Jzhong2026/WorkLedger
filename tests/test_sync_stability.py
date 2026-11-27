from __future__ import annotations

import json

import pytest

from workledger.services import sync_jira


def test_twg_runner_retries_transient_failures(monkeypatch):
    calls = []
    sleeps = []

    class Result:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) < 3:
            raise OSError("socket disconnect")
        return Result(0, "ok-output")

    monkeypatch.setattr(sync_jira.subprocess, "run", fake_run)
    monkeypatch.setattr(sync_jira, "sleep", lambda s: sleeps.append(s))
    assert sync_jira._twg_runner(["jira"]) == "ok-output"
    assert len(calls) == 3
    assert sleeps == [1, 3]


def test_twg_runner_gives_up_after_three(monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("socket disconnect")
    monkeypatch.setattr(sync_jira.subprocess, "run", fake_run)
    monkeypatch.setattr(sync_jira, "sleep", lambda s: None)
    with pytest.raises(OSError):
        sync_jira._twg_runner(["jira"])


def test_truncated_merges_current_user_query(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_jira, "LIMIT", 2)
    monkeypatch.setattr(sync_jira, "PAGE_SIZE", 2)
    calls = []

    def runner(args):
        calls.append(args)
        jql = args[args.index("--jql") + 1]
        if "assignee = currentUser()" in jql and "updated >=" not in jql:
            issues = [{"key": "RW-777", "summary": "Deep mine", "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                       "assignee": {"accountId": "acc-jason", "displayName": "JasonZhong"},
                       "created": "2026-01-01T00:00:00.000-0500", "updated": "2026-01-02T00:00:00.000-0500"}]
        else:
            issues = [{"key": f"RW-{n}", "summary": f"S{n}", "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                       "assignee": {"accountId": "acc-other", "displayName": "Other"},
                       "created": "2026-11-01T00:00:00.000-0500", "updated": f"2026-11-2{n}T00:00:00.000-0500"} for n in (1, 2)]
        payload = tmp_path / f"p{len(calls)}.json"
        payload.write_text(json.dumps({"data": {"issues": issues}}), encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    assert result["truncated"] is True
    # The identity probe (_my_account_id) also queries currentUser() without a
    # time window but with --limit 1; exclude it so we count only merge queries.
    mine_calls = [a for a in calls if "assignee = currentUser()" in a[a.index("--jql") + 1]
                  and "updated >=" not in a[a.index("--jql") + 1]
                  and a[a.index("--limit") + 1] != "1"]
    assert len(mine_calls) == 1
    assert conn.execute("SELECT 1 FROM work_events WHERE jira_key='RW-777'").fetchone() is not None