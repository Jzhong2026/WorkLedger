"""Regression tests against the REST routes used by the Web UI."""

import json
from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workledger import agent, db, mcp_server
from workledger.routers import api
from workledger.schemas import EventCreate
from workledger.services import events


@pytest.fixture
def client(monkeypatch, db_path):
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    monkeypatch.setattr(api, "_conn", lambda: db.get_connection(db_path))
    with TestClient(app) as client:
        yield client


def test_expanded_search_reuses_the_model_response_without_requerying(client, conn, monkeypatch):
    for summary in ("搜索修复", "Alpha search", "Other"):
        events.create_event(conn, EventCreate(
            event_type="manual", summary=summary, occurred_at=datetime(2026, 6, 1),
        ))
    expand = Mock(return_value={"ok": True, "keywords": "修复，alpha"})
    monkeypatch.setattr(agent, "expand_query", expand)

    first = client.post("/api/search/semantic", json={"question": "old search fixes", "page_size": 1})
    assert first.status_code == 200
    assert first.json()["total"] == 2
    second = client.post("/api/search/expanded", json={
        "expansion": first.json()["expansion"], "page": 2, "page_size": 1,
    })
    assert second.status_code == 200
    assert second.json()["items"][0]["summary"] == "搜索修复"
    assert second.json()["page"] == 2
    assert expand.call_count == 1


def test_unavailable_model_and_invalid_inputs_get_actionable_errors(client, monkeypatch):
    expand = Mock(return_value={"ok": False, "error": "CodeBuddy is disabled."})
    monkeypatch.setattr(agent, "expand_query", expand)

    assert client.post("/api/search/semantic", json={}).status_code == 422
    assert client.get("/api/search/fts?q=alpha&page_size=0").status_code == 422
    assert client.get("/api/insights?date_from=2026-06-02&date_to=2026-06-01").status_code == 422
    assert expand.call_count == 0
    response = client.post("/api/search/semantic", json={"question": "old search fixes"})
    assert response.status_code == 503
    assert response.json()["detail"] == "CodeBuddy is disabled."


def test_narrative_reports_exact_coverage_of_records_sent_to_model(client, conn, monkeypatch):
    now = datetime.now().strftime("%Y-%m-%d 00:00:00")
    with conn:
        conn.executemany(
            "INSERT INTO work_events (event_type, occurred_at, source_key, summary) VALUES (?, ?, ?, ?)",
            [("manual", now, f"fixture:{i}", f"Fixture #{i}") for i in range(501)],
        )
    synthesize = Mock(return_value={"ok": True, "narrative": "Model text"})
    monkeypatch.setattr(agent, "synthesize_narrative", synthesize)

    response = client.post("/api/export/narrative", json={"period": "all"})
    assert response.status_code == 200
    assert response.json()["coverage"]["totals"]["events"] == 501
    used = response.json()["coverage"]["included"]["events"]
    markdown = synthesize.call_args.args[0]
    assert 0 < used < 501
    assert used == markdown.count("**manual**")
    assert len(markdown) <= 6000


def test_empty_retrospective_skips_the_model_still_allows_markdown(client, monkeypatch):
    synthesize = Mock()
    monkeypatch.setattr(agent, "synthesize_narrative", synthesize)

    result = client.post("/api/export/narrative", json={"period": "all"})
    assert result.status_code == 422
    assert result.json()["detail"] == "There are no records in this period."
    assert not synthesize.called
    assert client.get("/api/export?period=all").status_code == 200


def test_mcp_and_rest_share_retrospective_period_pagination(client, conn, monkeypatch):
    events.create_event(conn, EventCreate(
        event_type="manual", summary="Earlier record", occurred_at=datetime(2020, 1, 1),
    ))
    events.create_event(conn, EventCreate(
        event_type="manual", summary="Recent record", occurred_at=datetime(2026, 6, 1),
    ))
    monkeypatch.setattr(mcp_server, "_conn", lambda: conn)

    mcp_result = json.loads(mcp_server.retrospective("all", page=2, page_size=1))
    rest_result = client.get("/api/retrospective?period=all&page=2&page_size=1").json()

    assert mcp_result == rest_result
    assert mcp_result["pages"] == 2
    assert mcp_result["events"][0]["summary"] == "Earlier record"
