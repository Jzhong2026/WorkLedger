from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from workledger.config import settings
from workledger.schemas import EventUpdate
from workledger.services import events, master_data, sync_bitbucket, sync_state

JASON_UUID = "{jason-uuid}"
_DEFAULT_UPDATED = (datetime.now(UTC) - timedelta(days=1)).isoformat()


@pytest.fixture()
def bb_settings(monkeypatch, conn):
    monkeypatch.setattr(settings, "atlassian_user_email", "jason@example.com")
    monkeypatch.setattr(settings, "atlassian_api_token", "token")
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    master_data.create_project(conn, name="RW (Atlas)", key="RW")


def _pr(pr_id=1, state="OPEN", title="feat(RW-901): something", updated=None, reviewers=None):
    return {
        "id": pr_id, "title": title, "state": state,
        "created_on": "2026-11-01T00:00:00+00:00",
        "updated_on": updated or _DEFAULT_UPDATED,
        "author": {"display_name": "JasonZhong", "uuid": JASON_UUID},
        "reviewers": reviewers or [],
        "links": {"html": {"href": f"https://bitbucket.org/transfinderorg/core/pull-requests/{pr_id}"}},
        "source": {"branch": {"name": "feat"}}, "destination": {"branch": {"name": "main"}},
    }


def _client(prs):
    def handler(request):
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"uuid": JASON_UUID, "display_name": "JasonZhong"})
        if request.url.path == "/2.0/repositories/transfinderorg/core/pullrequests":
            assert JASON_UUID in request.url.params["q"]
            return httpx.Response(200, json={"values": prs})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")


def test_anchor_created_with_identity_and_jira_link(conn, bb_settings):
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    assert result["ok"] is True
    row = conn.execute("SELECT * FROM work_events WHERE source_key='bitbucket:transfinderorg/core:pr:1'").fetchone()
    assert row["event_type"] == "pr_created"
    assert row["repo"] == "transfinderorg/core"
    assert row["jira_key"] == "RW-901"
    assert row["project_id"] is not None
    extra = json.loads(row["extra_json"])
    assert extra["state"] == "OPEN"
    assert extra["author_uuid"] == JASON_UUID
    assert extra["jira_keys"] == ["RW-901"]
    assert sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["detail"]["my_uuid"] == JASON_UUID


def test_rerun_unchanged_and_state_update_touches_anchor_only(conn, bb_settings):
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    assert result["repos"]["bitbucket:transfinderorg/core"]["unchanged"] == 1
    merged = _pr(state="MERGED", updated=datetime.now(UTC).isoformat())
    sync_bitbucket.sync_bitbucket(conn, client=_client([merged]))
    rows = conn.execute("SELECT * FROM work_events WHERE repo='transfinderorg/core'").fetchall()
    assert len(rows) == 1  # 不追加迁移事件
    assert json.loads(rows[0]["extra_json"])["state"] == "MERGED"


def test_edited_summary_preserved_and_stale_update_skipped(conn, bb_settings):
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    row = conn.execute("SELECT id FROM work_events WHERE pr_number=1").fetchone()
    events.update_event(conn, row["id"], EventUpdate(summary="My title"))
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(updated=datetime.now(UTC).isoformat())]))
    assert conn.execute("SELECT summary FROM work_events WHERE id=?", (row["id"],)).fetchone()[0] == "My title"
    older = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(updated=older)]))
    assert result["repos"]["bitbucket:transfinderorg/core"]["unchanged"] == 1


def test_reviewers_stored_for_needs_review(conn, bb_settings):
    reviewers = [{"display_name": "JasonZhong", "uuid": JASON_UUID, "approved": False}]
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(reviewers=reviewers)]))
    extra = json.loads(conn.execute("SELECT extra_json FROM work_events WHERE pr_number=1").fetchone()[0])
    assert extra["reviewers"] == [{"name": "JasonZhong", "uuid": JASON_UUID, "approved": False}]


def test_missing_credentials_records_error(conn, monkeypatch):
    monkeypatch.setattr(settings, "atlassian_user_email", "")
    monkeypatch.setattr(settings, "atlassian_api_token", "")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    result = sync_bitbucket.sync_bitbucket(conn)
    assert result["ok"] is False
    assert "credentials" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]


def test_user_fetch_failure_records_error_on_all_sources(conn, bb_settings):
    def handler(request):
        return httpx.Response(500)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")
    result = sync_bitbucket.sync_bitbucket(conn, client=client)
    assert result["ok"] is False
    assert "identity" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]


def test_user_non_json_response_records_error(conn, bb_settings):
    def handler(request):
        return httpx.Response(200, text="<html>login</html>")
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")
    result = sync_bitbucket.sync_bitbucket(conn, client=client)
    assert result["ok"] is False
    assert "identity" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]


def test_invalid_url_records_identity_error(conn, bb_settings):
    def handler(request):
        if request.url.path == "/2.0/user":
            raise httpx.InvalidURL("bad proxy")
        return httpx.Response(404)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")
    result = sync_bitbucket.sync_bitbucket(conn, client=client)
    assert result["ok"] is False
    assert "identity" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]


def test_duplicate_rows_deduped_by_id(conn, bb_settings):
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(), _pr()]))
    repo = result["repos"]["bitbucket:transfinderorg/core"]
    assert repo["created"] == 1
    assert repo["prs"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM work_events WHERE repo='transfinderorg/core'"
    ).fetchone()[0] == 1


def test_top_level_array_payloads_record_error_envelopes(conn, bb_settings):
    # /user 返回顶层数组 → 身份包络（TypeError 路径）
    def user_array(request):
        return httpx.Response(200, json=[1, 2, 3])
    client = httpx.Client(transport=httpx.MockTransport(user_array), base_url="https://api.bitbucket.org/2.0")
    result = sync_bitbucket.sync_bitbucket(conn, client=client)
    assert result["ok"] is False
    assert "identity" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]

    # pullrequests 返回顶层数组 → data.get 抛 AttributeError，必须落包络而非逃逸
    def pr_array(request):
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"uuid": JASON_UUID, "display_name": "JasonZhong"})
        return httpx.Response(200, json=[1, 2, 3])
    client2 = httpx.Client(transport=httpx.MockTransport(pr_array), base_url="https://api.bitbucket.org/2.0")
    result2 = sync_bitbucket.sync_bitbucket(conn, client=client2)
    assert result2["ok"] is False
    assert result2["repos"]["bitbucket:transfinderorg/core"]["ok"] is False
    assert "get" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]
