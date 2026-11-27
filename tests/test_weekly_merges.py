from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from workledger.config import settings
from workledger.schemas import EventCreate
from workledger.services import events, master_data, sync_bitbucket, work_review

JASON = "{jason-uuid}"


def _anchor(conn, pr_id, state, updated, created="2026-01-01T00:00:00+00:00", jira_key="RW-50"):
    return events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.fromisoformat(created),
        repo="transfinderorg/core", pr_number=pr_id, jira_key=jira_key,
        source_key=f"bitbucket:transfinderorg/core:pr:{pr_id}", source_agent="bitbucket-sync",
        summary=f"feat(RW-50): PR {pr_id}",
        extra_json=json.dumps({"state": state, "bitbucket_updated": updated,
                               "author_uuid": JASON, "reviewers": [], "jira_keys": [jira_key]}),
    ))


def test_weekly_includes_merged_pr_by_update_window(conn):
    monday = date.today() - timedelta(days=date.today().weekday())
    merged_at = (monday + timedelta(days=2)).isoformat() + "T12:00:00+00:00"
    _anchor(conn, 1, "MERGED", merged_at)                       # 本周合并，创建很久以前
    _anchor(conn, 2, "MERGED", "2026-01-05T00:00:00+00:00")     # 旧合并，不进
    _anchor(conn, 3, "OPEN", merged_at)                          # OPEN 不按合并进
    result = work_review.weekly_review(conn)
    pr_groups = [g for g in result["groups"] if g["title"] == "RW-50"]
    assert pr_groups, "merged PR should group under its Jira key"
    ids = [e["pr_number"] for g in result["groups"] for e in g["events"] if e.get("pr_number")]
    assert 1 in ids and 2 not in ids and 3 not in ids


@pytest.fixture()
def bb(monkeypatch, conn):
    monkeypatch.setattr(settings, "atlassian_user_email", "j@example.com")
    monkeypatch.setattr(settings, "atlassian_api_token", "t")
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    monkeypatch.setattr(settings, "sync_record_merge_accomplishments", True)
    master_data.create_project(conn, name="RW", key="RW")


def _pr(state, updated):
    return {"id": 9, "title": "feat(RW-50): x", "state": state,
            "created_on": "2026-11-01T00:00:00+00:00", "updated_on": updated,
            "author": {"display_name": "JasonZhong", "uuid": JASON}, "reviewers": [],
            "links": {"html": {"href": "https://bitbucket.org/transfinderorg/core/pull-requests/9"}},
            "source": {"branch": {"name": "feat"}}, "destination": {"branch": {"name": "main"}}}


def _client(prs):
    def handler(request):
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"uuid": JASON})
        return httpx.Response(200, json={"values": prs})
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")


def test_merge_transition_writes_idempotent_accomplishment(conn, bb):
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("OPEN", recent)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 0
    newer = datetime.now(UTC).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", newer)]))
    rows = conn.execute("SELECT * FROM accomplishments").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_key"] == "bitbucket:transfinderorg/core:pr:9".replace("bitbucket:", "bitbucket-merge:", 1)
    assert rows[0]["event_id"] is not None
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", newer)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 1


def test_merge_accomplishments_can_be_disabled(conn, bb, monkeypatch):
    monkeypatch.setattr(settings, "sync_record_merge_accomplishments", False)
    recent = datetime.now(UTC).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", recent)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 0