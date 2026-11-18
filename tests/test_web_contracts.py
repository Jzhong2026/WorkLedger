import sqlite3
from contextlib import closing
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from workledger import agent
from workledger import app as web
from workledger.routers import api


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setattr(web.settings, "workledger_data_dir", str(db_path.parent / "startup"))
    with closing(sqlite3.connect(db_path, check_same_thread=False)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        monkeypatch.setattr(api, "_conn", lambda: conn)
        with TestClient(web.create_app()) as client:
            yield client


def test_event_can_be_linked_from_accomplishment_and_case(client):
    occurred = datetime.now().isoformat()
    source = client.post("/api/events", json={
        "event_type": "fix", "occurred_at": occurred, "summary": "Fixed a validation gap",
    }).json()
    payload = {"title": "Validation", "occurred_at": occurred, "event_id": source["id"]}
    for path in ("accomplishments", "cases"):
        response = client.post(f"/api/{path}", json=payload)
        assert response.status_code == 201
        assert response.json()["event_id"] == source["id"]
        missing_event = client.post(f"/api/{path}", json={**payload, "event_id": 9876})
        assert missing_event.status_code == 404


def test_management_writes_validate_invalid_input(client):
    assert client.post("/api/projects", json={"name": "No key"}).status_code == 422
    project = client.post("/api/projects", json={"name": "Demo", "key": "D"}).json()
    assert client.post("/api/projects", json={"name": "Duplicate", "key": "D"}).status_code == 409
    result = client.post("/api/sprints", json={
        "project_id": project["id"], "name": "Reversed", "start_date": "2026-11-30",
        "end_date": "2026-11-01",
    })
    assert result.status_code == 422


def test_spa_serves_index_and_only_explicit_static_assets(client, db_path, monkeypatch):
    dist = db_path.parent / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>WorkLedger</h1>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("// bundled asset", encoding="utf-8")
    (dist / "local-build-notes.txt").write_text("Build scratch", encoding="utf-8")
    monkeypatch.setattr(web, "FRONTEND_DIST", dist)
    with TestClient(web.create_app()) as frontend:
        assert frontend.get("/search").text == "<h1>WorkLedger</h1>"
        assert frontend.get("/assets/app.js").text == "// bundled asset"
        assert frontend.get("/local-build-notes.txt").text == "<h1>WorkLedger</h1>"
        assert frontend.get("/api/missing-route").status_code == 404


def test_disabled_agent_never_starts_model(monkeypatch):
    monkeypatch.setattr(agent.settings, "agent_enabled", False)
    monkeypatch.setattr(agent.settings, "codebuddy_api_key", "test-key")
    monkeypatch.setattr(agent, "_cli_base", lambda: pytest.fail("Disabled agent checked CLI"))
    result = agent.structure_note("A local note")
    assert result["ok"] is False
    assert "disabled" in result["error"].lower()


def test_capture_and_manual_record_when_ai_is_disabled(client, monkeypatch):
    monkeypatch.setattr(agent.settings, "agent_enabled", False)
    note = client.post("/api/inbox", json={"raw_text": "A captured work note"}).json()
    assert client.post(f"/api/inbox/{note['id']}/structure").status_code == 503
    assert client.get("/api/inbox").json()[0]["status"] == "raw"
    manual_url = f"/api/inbox/{note['id']}/commit"
    first = client.post(manual_url, json={"summary": "Edited manual event"})
    second = client.post(manual_url, json={"summary": "Edited manual event"})
    assert first.status_code == second.status_code == 200
    assert first.json()["event"]["summary"] == "Edited manual event"
    assert first.json()["event"]["id"] == second.json()["event"]["id"]
    assert client.get("/api/inbox").json()[0]["status"] == "committed"


def test_review_and_confirm_updates_are_visible_through_web(client, monkeypatch):
    def structure_locally(text, *, model=None):
        return {"ok": True, "events": [{
            "event_type": "fix", "summary": "Draft", "detail": text,
        }]}

    monkeypatch.setattr(agent, "structure_note", structure_locally)
    note_id = client.post("/api/inbox", json={"raw_text": "Original note"}).json()["id"]
    draft = client.post(f"/api/inbox/{note_id}/structure").json()["drafts"][0]
    assert draft["draft"]["detail"] == "Original note"
    draft_url = f"/api/drafts/{draft['id']}"
    updated = client.patch(draft_url, json={"summary": "Saved title"})
    assert updated.json()["draft"]["summary"] == "Saved title"
    final = client.post(f"{draft_url}/confirm", json={"summary": "Reviewed and confirmed"}).json()
    assert final["event"]["summary"] == "Reviewed and confirmed"
    assert client.get("/api/drafts").json() == []
    assert client.patch(draft_url, json={"summary": "Late edit"}).status_code == 409
