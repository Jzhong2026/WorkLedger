"""Reusable lessons stay grounded and outside automatic recall until reviewed."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from workledger.db import DatabaseError
from workledger.learning_models import LessonCreate, LessonUpdate
from workledger.schemas import EventCreate
from workledger.services import events, learning


def _item(conn, title, project_id=None):
    with conn:
        return conn.execute(
            """INSERT INTO work_items
               (title, project_id, stage, needs_decision, version, request_fingerprint, created_at, updated_at)
               VALUES (?, ?, 'active', 0, 1, 'test', datetime('now'), datetime('now')) RETURNING id""",
            (title, project_id),
        ).fetchone()[0]


def _lesson(conn, item, **overrides):
    return learning.create_lesson(conn, LessonCreate(**{
        "source_work_item_id": item,
        "kind": "process",
        "title": "Collect reproducible search evidence",
        "trigger": "A fuzzy match returns the wrong person",
        "first_step": "Capture the input and expected result",
        "tags": ["fuzzy match", "search"],
        **overrides,
    }))


def test_recall_needs_review_and_explains_cross_project_relevance(conn):
    with conn:
        project = conn.execute("INSERT INTO projects (name, key) VALUES ('Atlas', 'AI') RETURNING id").fetchone()[0]
        another = conn.execute("INSERT INTO projects (name, key) VALUES ('Core', 'CORE') RETURNING id").fetchone()[0]
    source = _item(conn, "Search regression", project)
    lesson = _lesson(conn, source)
    assert _lesson(conn, source)["id"] == lesson["id"]
    assert lesson["status"] == "candidate"
    assert learning.recall_lessons(conn, "Investigate a fuzzy match issue", project_id=another) == []

    learning.review_lesson(conn, lesson["id"], "confirmed")
    recommendations = learning.recall_lessons(conn, "Investigate a fuzzy match issue", project_id=another)
    assert [row["id"] for row in recommendations] == [lesson["id"]]
    assert recommendations[0]["source_work_item_title"] == "Search regression"
    assert any("Atlas" in reason for reason in recommendations[0]["reasons"])
    assert learning.recall_lessons(conn, "Payroll data extraction", project_id=project) == []

    edited = learning.update_lesson(conn, lesson["id"], LessonUpdate(first_step="Record the failing input"))
    assert edited["status"] == "candidate"
    assert learning.recall_lessons(conn, "fuzzy match") == []
    learning.review_lesson(conn, lesson["id"], "declined")
    retry = _lesson(conn, source)
    assert retry["id"] == lesson["id"]
    assert retry["status"] == "declined"
    assert retry["first_step"] == "Record the failing input"


def test_reuse_updates_one_outcome_per_lesson_and_item(conn):
    source = _item(conn, "Original case")
    later = _item(conn, "Follow-up case")
    lesson = _lesson(conn, source)
    with pytest.raises(DatabaseError, match="Confirm"):
        learning.record_lesson_use(conn, lesson["id"], work_item_id=later, outcome="applied")
    learning.review_lesson(conn, lesson["id"], "confirmed")
    with pytest.raises(DatabaseError, match="different"):
        learning.record_lesson_use(conn, lesson["id"], work_item_id=source, outcome="applied")
    first = learning.record_lesson_use(conn, lesson["id"], work_item_id=later, outcome="applied")
    repeat = learning.record_lesson_use(conn, lesson["id"], work_item_id=later, outcome="applied")
    assert first == repeat
    completed = learning.record_lesson_use(
        conn, lesson["id"], work_item_id=later, outcome="helped", detail="Faster triage",
    )
    assert completed["outcome"] == "helped"
    assert completed["created_at"] == first["created_at"]
    saved = learning.get_lesson(conn, lesson["id"])
    assert saved["uses"] == [completed]
    assert saved["use_count"] == 1
    history = conn.execute(
        "SELECT outcome, detail FROM lesson_use_history WHERE lesson_id=? ORDER BY id", (lesson["id"],),
    )
    assert [tuple(row) for row in history] == [("applied", None), ("helped", "Faster triage")]


def test_confirmed_chinese_lesson_matches_short_literal_trigger(conn):
    source = _item(conn, "历史案例")
    lesson = _lesson(conn, source, title="搜索验证", trigger="姓名模糊匹配", tags=["匹配"])
    learning.review_lesson(conn, lesson["id"], "confirmed")
    assert learning.recall_lessons(conn, "检查姓名匹配")[0]["id"] == lesson["id"]


def test_model_draft_uses_linked_local_evidence_and_stays_a_candidate(conn, monkeypatch):
    item = _item(conn, "Validate fuzzy match")
    source = events.create_event(conn, EventCreate(
        event_type="verification",
        occurred_at=datetime(2026, 1, 4),
        summary="Confirmed search ranking with fixtures",
        evidence_url="https://example.test/proof",
        verification_result="A quick fixture exposed the failure",
        verification_done=True,
    ))
    propose = Mock(return_value={"ok": True, "candidate": {
        "kind": "process", "title": "Create a focused fixture",
        "trigger": "Fuzzy matching ranking looks wrong",
        "first_step": "Add a fixture with two plausible candidates",
    }})
    monkeypatch.setattr(learning, "propose_lesson", propose)

    with pytest.raises(DatabaseError, match="Link an event"):
        learning.draft_lesson(conn, item)
    with pytest.raises(DatabaseError, match="linked to this work item"):
        learning.draft_lesson(conn, item, source_event_id=source["id"])
    assert not propose.called

    with conn:
        conn.execute("UPDATE work_items SET source_event_id=? WHERE id=?", (source["id"], item))
    draft = learning.draft_lesson(conn, item, source_event_id=source["id"])
    assert draft["status"] == "candidate"
    assert draft["origin"] == "codebuddy"
    assert draft["evidence_url"] == source["evidence_url"]
    assert propose.call_args.args[0]["verification_result"] == source["verification_result"]
    assert "evidence_url" not in propose.call_args.args[0]
    assert learning.recall_lessons(conn, "fuzzy matching ranking") == []

    learning.review_lesson(conn, draft["id"], "confirmed")
    repeated = learning.draft_lesson(conn, item, source_event_id=source["id"])
    assert repeated["id"] == draft["id"]
    assert repeated["status"] == "confirmed"
    assert propose.call_count == 1

