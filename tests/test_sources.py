from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from workledger.schemas import EventCreate
from workledger.services import events, sources, sync_state


def _event(conn, summary, source_agent=None, extra=None, jira_key=None, repo=None, pr_number=None):
    return events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=datetime.now(UTC), summary=summary,
        source_agent=source_agent, jira_key=jira_key, repo=repo, pr_number=pr_number,
        extra_json=json.dumps(extra) if extra is not None else None,
    ))


def _identities(conn):
    sync_state.record_success(conn, "jira", {"my_account_id": "acc-jason"})
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason}"})


def test_event_source_mapping():
    assert sources.event_source("jira-import") == "jira"
    assert sources.event_source("bitbucket-sync") == "bitbucket"
    assert sources.event_source("inbox") == "human"
    assert sources.event_source(None) == "human"


def test_is_mine_row():
    assert sources.is_mine_row(None, None, "acc-jason", "{jason}") is True
    assert sources.is_mine_row("jira-import", json.dumps({"assignee_account_id": "acc-jason"}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("jira-import", json.dumps({"assignee_account_id": "acc-other"}), "acc-jason", "{jason}") is False
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{jason}"}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{o}", "reviewers": [{"uuid": "{jason}"}]}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{o}", "reviewers": []}), "acc-jason", "{jason}") is False
    assert sources.is_mine_row("jira-import", None, None, None) is False


def test_search_events_scope_mine(conn):
    _identities(conn)
    mine_ticket = _event(conn, "mine ticket", "jira-import", {"assignee_account_id": "acc-jason"}, jira_key="RW-1")
    _event(conn, "other ticket", "jira-import", {"assignee_account_id": "acc-other"}, jira_key="RW-2")
    mine_pr = _event(conn, "mine pr", "bitbucket-sync", {"author_uuid": "{jason}"}, repo="transfinderorg/core", pr_number=1)
    _event(conn, "reviewed pr", "bitbucket-sync", {"author_uuid": "{o}", "reviewers": [{"uuid": "{jason}"}]}, repo="transfinderorg/core", pr_number=2)
    _event(conn, "other pr", "bitbucket-sync", {"author_uuid": "{o}", "reviewers": []}, repo="transfinderorg/core", pr_number=3)
    human = _event(conn, "human note", None)
    items, total = events.search_events(conn, scope="mine")
    assert total == 4
    assert {i["id"] for i in items} == {mine_ticket["id"], mine_pr["id"], human["id"]} | {i["id"] for i in items if i["summary"] == "reviewed pr"}
    _, all_total = events.search_events(conn)
    assert all_total == 6
    with pytest.raises(ValueError):
        events.search_events(conn, scope="bogus")


def test_search_events_mine_without_identities_keeps_human(conn):
    _event(conn, "jira row", "jira-import", {"assignee_account_id": "acc-jason"})
    human = _event(conn, "human note", None)
    items, total = events.search_events(conn, scope="mine")
    assert total == 1
    assert items[0]["id"] == human["id"]