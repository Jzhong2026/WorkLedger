"""Workflow regressions for linked work items and coherent, retriable handoffs."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from workledger import app as web
from workledger.db import DatabaseError, close_connection, get_connection
from workledger.learning_models import LessonCreate
from workledger.schemas import EventCreate, TodoCreate
from workledger.services import events, learning, master_data, todos, work_items
from workledger.work_item_models import HandoffCreate, HandoffTodo, WorkItemCreate


def _event(conn, summary: str, jira_key: str | None = None):
    return events.create_event(
        conn, EventCreate(event_type="manual", summary=summary, jira_key=jira_key, occurred_at=datetime.now(UTC)),
    )


def test_historical_records_are_discoverable_without_synthesizing_items(conn):
    project = master_data.create_project(conn, name="Atlas", key="ATL")
    parent = _event(conn, "Parent story", jira_key="ATL-1")
    child = _event(conn, "Imported task", jira_key="ATL-2")
    with conn:
        conn.execute("UPDATE work_events SET project_id = ? WHERE id IN (?, ?)", (project["id"], parent["id"], child["id"]))
        conn.execute("UPDATE work_events SET parent_event_id = ? WHERE id = ?", (parent["id"], child["id"]))

    records, total = work_items.discover_events(conn, project_id=project["id"], jira_key="atl-2")
    assert total == 1
    assert records[0]["id"] == child["id"]
    assert "stage" not in records[0]
    assert work_items.list_work_items(conn, project_id=project["id"]) == ([], 0)

    item = work_items.create_work_item(conn, WorkItemCreate(title="Follow up", source_event_id=child["id"]))
    assert item["project_id"] == project["id"]
    assert item["jira_key"] == "ATL-2"
    context = work_items.get_work_item_context(conn, item["id"])
    assert context["source_event"]["id"] == child["id"]
    assert context["parent_event"]["id"] == parent["id"]
    assert context["history"] == []


def test_create_idempotency_distinguishes_different_requests(conn):
    data = WorkItemCreate(title="Investigate search", source_key="test:create:1")
    first = work_items.create_work_item(conn, data)
    second = work_items.create_work_item(conn, data)
    assert first["id"] == second["id"]
    assert first["version"] == 1
    with pytest.raises(DatabaseError, match="source key") as error:
        work_items.create_work_item(conn, data.model_copy(update={"title": "Different work"}))
    assert error.value.status_code == 409


def test_handoff_records_new_evidence_and_followup_and_links_existing_records(conn):
    project = master_data.create_project(conn, name="Atlas", key="ATL")
    item = work_items.create_work_item(conn, WorkItemCreate(title="Search", project_id=project["id"], blocker="Pending"))
    linked = _event(conn, "Existing evidence")
    pending = todos.create_todo(conn, TodoCreate(title="Existing follow-up", next_followup="2026-06-03"))
    done = todos.create_todo(conn, TodoCreate(title="Resolved follow-up", status="done", due_date="2026-06-01"))
    context = work_items.record_handoff(
        conn, item["id"], HandoffCreate(
            expected_version=1, source_key="handoff:1", summary="Search tests verified",
            stage="verification", actor="Codex", owner="QA", blocker=None, needs_decision=True,
            next_step="Review evidence", last_verified_result="12 checks passed",
            event_ids=[linked["id"]], todo_ids=[pending["id"], done["id"]],
            todo=HandoffTodo(title="Follow up with QA", due_date=date(2026, 6, 4)),
        ),
    )
    current = context["item"]
    assert current["version"] == 2
    assert current["stage"] == "verification"
    assert current["owner"] == "QA"
    assert current["blocker"] is None
    assert current["needs_decision"] is True
    assert current["linked_followup_date"] == "2026-06-03"
    assert work_items.list_work_items(conn, open_only=True)[0][0]["linked_followup_date"] == "2026-06-03"
    handoff = context["history"][0]
    assert handoff["actor"] == "Codex"
    assert handoff["previous_stage"] == "active"
    assert handoff["stage"] == "verification"
    assert handoff["last_verified_result"] == "12 checks passed"
    assert handoff["created_at"]
    generated = next(record for record in context["events"] if record["id"] == handoff["event_id"])
    assert generated["event_type"] == "verification"
    assert generated["project_id"] == project["id"]
    assert generated["verification_result"] == "12 checks passed"
    assert generated["verification_done"] is True
    assert {todo["title"] for todo in context["todos"]} == {
        "Existing follow-up", "Resolved follow-up", "Follow up with QA",
    }
    assert next(todo for todo in context["todos"] if todo["id"] == handoff["todo_id"])["event_id"] == generated["id"]


def test_handoff_replay_precedes_version_conflict_and_stage_does_not_claim_verification(conn):
    item = work_items.create_work_item(conn, WorkItemCreate(title="Search", last_verified_result="Earlier tests"))
    first = HandoffCreate(expected_version=1, summary="Awaiting assignment", stage="waiting", source_key="test:h1")
    handoff = work_items.record_handoff(conn, item["id"], first)["handoff"]
    work_items.record_handoff(conn, item["id"], HandoffCreate(expected_version=2, summary="Closed", stage="done"))
    replay = work_items.record_handoff(conn, item["id"], first)
    assert replay["replayed"] is True
    assert replay["handoff"]["id"] == handoff["id"]
    assert replay["item"]["version"] == 3
    assert replay["item"]["last_verified_result"] == "Earlier tests"
    assert all(not event["verification_done"] for event in replay["events"])
    assert len(replay["history"]) == 2
    assert work_items.list_work_items(conn, open_only=True) == ([], 0)
    with pytest.raises(DatabaseError, match="version") as stale:
        work_items.record_handoff(conn, item["id"], HandoffCreate(expected_version=1, summary="Out of date"))
    assert stale.value.status_code == 409
    with pytest.raises(DatabaseError, match="source key") as reused:
        work_items.record_handoff(conn, item["id"], first.model_copy(update={"summary": "Changed"}))
    assert reused.value.status_code == 409


def test_failed_handoff_rolls_back_item_event_todo_and_links(conn):
    item = work_items.create_work_item(conn, WorkItemCreate(title="Search"))
    conn.execute(
        """CREATE TRIGGER reject_handoff BEFORE INSERT ON work_item_handoffs
           BEGIN SELECT RAISE(ABORT, 'forced history failure'); END"""
    )
    data = HandoffCreate(
        expected_version=1, summary="Status", stage="waiting", source_key="retryable-handoff",
        todo=HandoffTodo(title="Try again"),
    )
    with pytest.raises((DatabaseError, sqlite3.IntegrityError), match="forced history failure"):
        work_items.record_handoff(conn, item["id"], data)
    context = work_items.get_work_item_context(conn, item["id"])
    assert context["item"]["version"] == 1
    assert context["item"]["stage"] == "active"
    assert context["events"] == context["todos"] == context["history"] == []
    assert events.search_events(conn)[1] == todos.list_todos(conn)[1] == 0
    conn.execute("DROP TRIGGER reject_handoff")
    assert work_items.record_handoff(conn, item["id"], data)["item"]["version"] == 2


def test_concurrent_handoffs_detect_stale_version(conn, db_path):
    item = work_items.create_work_item(conn, WorkItemCreate(title="Search"))
    start = Barrier(2)

    def handoff(index: int):
        start.wait(timeout=5)
        try:
            work_items.record_handoff(
                get_connection(db_path), item["id"], HandoffCreate(expected_version=1, summary=f"Update {index}"),
            )
            return 200
        except DatabaseError as error:
            return error.status_code
        finally:
            close_connection(db_path)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(handoff, range(2))) == [200, 409]
    context = work_items.get_work_item_context(conn, item["id"])
    assert context["item"]["version"] == 2
    assert len(context["history"]) == len(context["events"]) == 1


def test_context_reuses_confirmed_lessons_with_source_and_no_self_matches(conn):
    old = work_items.create_work_item(conn, WorkItemCreate(title="SQLite export investigation"))
    current = work_items.create_work_item(conn, WorkItemCreate(title="SQLite export regression"))
    draft = learning.create_lesson(conn, LessonCreate(
        kind="skill", title="Check SQLite export first", source_work_item_id=old["id"],
        trigger="SQLite export unexpectedly stops early", first_step="Count the source records",
    ))
    assert work_items.get_work_item_context(conn, current["id"])["related_lessons"] == []
    learning.review_lesson(conn, draft["id"], "confirmed")
    result = work_items.get_work_item_context(conn, current["id"])["related_lessons"]
    assert [lesson["id"] for lesson in result] == [draft["id"]]
    assert result[0]["source_work_item_id"] == old["id"]
    assert result[0]["reasons"]
    assert work_items.get_work_item_context(conn, old["id"])["related_lessons"] == []


def test_lesson_read_failure_preserves_handoff_and_reports_partial_context(conn, monkeypatch):
    def failed_recall(*args, **kwargs):
        raise sqlite3.OperationalError("Lesson read failed")

    monkeypatch.setattr(learning, "recall_lessons", failed_recall)
    item = work_items.create_work_item(conn, WorkItemCreate(title="Search"))
    result = work_items.record_handoff(conn, item["id"], HandoffCreate(expected_version=1, summary="Ready"))
    assert result["item"]["version"] == 2
    assert result["history"] and result["events"]
    assert result["related_lessons"] == []
    assert result["related_lessons_error"]


def test_work_item_routes_use_the_persisted_context_and_version_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(web.settings, "workledger_data_dir", str(tmp_path / "work-item-rest"))
    with TestClient(web.create_app()) as client:
        assert client.get("/api/work-items/discover").json()["total"] == 0
        response = client.post("/api/work-items", json={"title": "Work tracker", "needs_decision": True})
        assert response.status_code == 201
        item_id = response.json()["id"]
        path = f"/api/work-items/{item_id}"
        handoff = {"expected_version": 1, "summary": "Proof checked", "stage": "verification"}
        assert client.post(f"{path}/handoffs", json=handoff).status_code == 201
        stale = client.post(f"{path}/handoffs", json=handoff)
        assert stale.status_code == 409
        context = client.get(path).json()
        assert context["item"]["stage"] == "verification"
        assert context["item"]["version"] == 2
        assert context["item"]["needs_decision"] is True
        assert len(context["history"]) == len(context["events"]) == 1
        assert client.get("/api/work-items?open_only=true").json()["items"][0]["id"] == item_id
