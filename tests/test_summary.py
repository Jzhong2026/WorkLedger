from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from workledger.config import settings
from workledger.schemas import EventCreate, TodoCreate
from workledger.services import events, jira_import, master_data, summary, sync_state, todos
from workledger.work_item_models import WorkItemCreate
from workledger.services import work_items


@pytest.fixture()
def seeded(conn, monkeypatch):
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    rw = master_data.create_project(conn, name="RW (Atlas)", key="RW")
    wl = master_data.create_project(conn, name="WorkLedger", key="WL")
    today = date.today()
    recent = (today - timedelta(days=2)).isoformat()
    old = (today - timedelta(days=40)).isoformat()
    jira_import.import_issues(conn, [
        {"key": "RW-1", "summary": "Open one", "created": f"{old}T09:00:00+0800",
         "updated": f"{recent}T09:00:00+0800",
         "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
        {"key": "RW-2", "summary": "Legacy done", "created": f"{old}T09:00:00+0800",
         "status": {"name": "已完成"}},
        {"key": "RW-3", "summary": "Old backlog", "created": f"{old}T09:00:00+0800",
         "updated": f"{old}T09:00:00+0800",
         "status": {"name": "In Backlog", "statusCategory": {"key": "new"}}},
    ], project_key="RW", project_name="RW")
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.now(UTC), repo="transfinderorg/core",
        pr_number=10, source_key="bitbucket:transfinderorg/core:pr:10", source_agent="bitbucket-sync",
        summary="feat(RW-1): open PR", jira_key="RW-1",
        extra_json=json.dumps({"state": "OPEN", "bitbucket_updated": datetime.now(UTC).isoformat(),
                               "author": "JasonZhong", "author_uuid": "{jason-uuid}",
                               "reviewers": [{"name": "JasonZhong", "uuid": "{jason-uuid}", "approved": False}],
                               "jira_keys": ["RW-1"], "url": "https://bitbucket.org/pr/10"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.now(UTC) - timedelta(days=50),
        repo="transfinderorg/core", pr_number=11,
        source_key="bitbucket:transfinderorg/core:pr:11", source_agent="bitbucket-sync",
        summary="old merged", extra_json=json.dumps({"state": "MERGED", "bitbucket_updated": old + "T00:00:00+00:00",
                                                    "author": "Other", "author_uuid": "{other}",
                                                    "reviewers": [], "jira_keys": []}),
    ))
    overdue = todos.create_todo(conn, TodoCreate(title="Overdue WL", due_date=(today - timedelta(days=1)).isoformat()))
    conn.execute("UPDATE todos SET project_id=? WHERE id=?", (wl["id"], overdue["id"]))
    rw_event = events.create_event(conn, EventCreate(event_type="manual", occurred_at=datetime.now(UTC), summary="RW context"))
    conn.execute("UPDATE work_events SET project_id=? WHERE id=?", (rw["id"], rw_event["id"]))
    todos.create_todo(conn, TodoCreate(title="RW open", event_id=rw_event["id"]))
    work_items.create_work_item(conn, WorkItemCreate(title="Track RW-1", jira_key="RW-1", project_id=rw["id"]))
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason-uuid}"})
    return rw


def test_counts_open_done_and_chinese_fallback(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert result["tickets"]["counts"]["open"] == 2
    assert result["tickets"]["counts"]["done"] == 1
    assert result["tickets"]["counts"]["by_status"]["已完成"] == 1
    keys = {t["key"] for t in result["tickets"]["open"]}
    assert keys == {"RW-1", "RW-3"}


def test_changed_window_and_pr_counts(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert {t["key"] for t in result["tickets"]["changed_in_window"]} == {"RW-1"}
    assert result["prs"]["counts"] == {"open": 1, "merged": 0, "needs_review": 1}
    assert result["prs"]["items"][0]["mine"]["needs_my_review"] is True
    assert result["tickets"]["open"][0]["work_item_id"] is not None


def test_todos_overdue_global_and_work_items(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert result["todos"]["overdue_global"][0]["project_key"] == "WL"
    assert result["todos"]["project_open"][0]["title"] == "RW open"
    assert result["work_items"]["open"] == 1


def test_unknown_key_and_bad_window(seeded, conn):
    with pytest.raises(KeyError):
        summary.project_summary(conn, "NOPE")
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "91d")
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "abc")


def test_sync_section_present(seeded, conn):
    result = summary.project_summary(conn, "RW")
    assert "sync" in result
    assert result["window"]["days"] == 7