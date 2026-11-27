from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workledger.db import get_connection
from workledger.routers import summary as summary_router
from workledger.schemas import AccomplishmentCreate, EventCreate
from workledger.services import events, master_data, retrospectives, summary, sync_state, work_review
from workledger.services import export as export_service


@pytest.fixture()
def seeded(conn):
    sync_state.record_success(conn, "jira", {"my_account_id": "acc-jason"})
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason}"})
    rw = master_data.create_project(conn, name="RW (Atlas)", key="RW")
    now = datetime.now(UTC)
    events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=now, summary="My ticket", source_agent="jira-import",
        jira_key="RW-1", project_id=None,
        extra_json=json.dumps({"assignee_account_id": "acc-jason", "status": "In Progress", "status_category": "indeterminate"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=now, summary="Other ticket", source_agent="jira-import",
        jira_key="RW-2",
        extra_json=json.dumps({"assignee_account_id": "acc-other", "status": "In Progress", "status_category": "indeterminate"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="My PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=1,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": "{jason}", "reviewers": [], "bitbucket_updated": now.isoformat()}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="Other PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=2,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": "{o}", "reviewers": [], "bitbucket_updated": now.isoformat()}),
    ))
    conn.execute("UPDATE work_events SET project_id=? WHERE jira_key IS NOT NULL OR repo IS NOT NULL", (rw["id"],))
    retrospectives.create_accomplishment(conn, AccomplishmentCreate(title="Manual win", occurred_at=now))
    return rw


def test_summary_mine_filters_tickets_and_prs(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d", scope="mine")
    assert result["scope"] == "mine"
    assert {t["key"] for t in result["tickets"]["open"]} == {"RW-1"}
    assert result["tickets"]["counts"]["open"] == 1
    assert {p["pr_number"] for p in result["prs"]["items"]} == {1}
    all_result = summary.project_summary(conn, "RW", "7d")
    assert all_result["scope"] == "all"
    assert all_result["tickets"]["counts"]["open"] == 2
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "7d", scope="bogus")


def test_export_mine_filters_events_keeps_accomplishments(seeded, conn):
    md = export_service.export_markdown(conn, "all", scope="mine")
    assert "My ticket" in md and "My PR" in md
    assert "Other ticket" not in md and "Other PR" not in md
    assert "Manual win" in md


def test_weekly_mine_filters_groups(seeded, conn):
    result = work_review.weekly_review(conn, scope="mine")
    summaries = [e["summary"] for g in result["groups"] for e in g["events"]]
    assert "My ticket" in summaries and "My PR" in summaries
    assert "Other ticket" not in summaries and "Other PR" not in summaries
    assert len(result["accomplishments"]) == 1


def test_summary_mine_without_identities_matches_nothing(conn):
    # Fresh conn: no sync_state identities recorded, so account_id/my_uuid are None.
    # None == None must not count as a mine match (spec: 身份缺失时 mine 分支不匹配).
    rw = master_data.create_project(conn, name="RW (Atlas)", key="RW")
    now = datetime.now(UTC)
    events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=now, summary="Unassigned ticket", source_agent="jira-import",
        jira_key="RW-1", project_id=None,
        extra_json=json.dumps({"assignee_account_id": None, "status": "In Progress", "status_category": "indeterminate"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="Anon PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=1,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": None, "reviewers": [], "bitbucket_updated": now.isoformat()}),
    ))
    # Reviewer lacking uuid must not match a None my_uuid either.
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="Uuid-less reviewer PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=2,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": "{o}", "reviewers": [{"display_name": "No UUID"}], "bitbucket_updated": now.isoformat()}),
    ))
    conn.execute("UPDATE work_events SET project_id=? WHERE jira_key IS NOT NULL OR repo IS NOT NULL", (rw["id"],))
    conn.commit()

    mine = summary.project_summary(conn, "RW", "7d", scope="mine")
    assert mine["tickets"]["open"] == []
    assert mine["prs"]["items"] == []

    all_result = summary.project_summary(conn, "RW", "7d")
    by_number = {p["pr_number"]: p for p in all_result["prs"]["items"]}
    assert by_number[1]["mine"]["authored"] is False
    assert by_number[1]["mine"]["needs_my_review"] is False
    assert by_number[2]["mine"]["reviewing"] is False
    assert by_number[2]["mine"]["needs_my_review"] is False


def test_summary_router_scope_validation(seeded, conn, db_path, monkeypatch):
    app = FastAPI()
    app.include_router(summary_router.router, prefix="/api")
    # TestClient runs sync endpoints in a worker thread; use the thread-local
    # connection factory like test_sync_api/test_workflow_api instead of the
    # main-thread fixture connection.
    monkeypatch.setattr(summary_router, "_conn", lambda: get_connection(db_path))
    with TestClient(app) as client:
        assert client.get("/api/summary/project?key=RW&scope=mine").json()["scope"] == "mine"
        assert client.get("/api/summary/project?key=RW&scope=bogus").status_code == 422
