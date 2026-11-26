from datetime import date

import pytest

from workledger import agent
from workledger.db import DatabaseError
from workledger.schemas import EventCreate
from workledger.services import events, work_review


def add_event(conn, day, summary, **kwargs):
    return events.create_event(conn, EventCreate(
        event_type="fix", occurred_at=day, summary=summary, **kwargs,
    ))


def test_week_groups_pr_events_and_excludes_next_monday(conn):
    add_event(conn, "2026-11-16T00:00", "First fix", repo="example", pr_number=3)
    add_event(conn, "2026-11-22T23:59", "Second fix", repo="example", pr_number=3)
    add_event(conn, "2026-11-23T00:00", "Next week")
    report = work_review.weekly_review(conn, date(2026, 11, 18))
    assert report["start"] == "2026-11-16"
    assert report["end"] == "2026-11-22"
    assert len(report["groups"]) == 1
    assert [source["summary"] for source in report["groups"][0]["events"]] == ["Second fix", "First fix"]


def test_generated_candidate_needs_a_weekly_source(conn, monkeypatch):
    add_event(conn, "2026-11-18T09:30", "Verified local result")
    monkeypatch.setattr(agent, "propose_with_sources", lambda *args: [
        {"text": "Unrelated claim", "source_ids": [500]}
    ])
    with pytest.raises(DatabaseError, match="source"):
        work_review.weekly_candidates(conn, date(2026, 11, 18))


def test_empty_week_does_not_contact_model(conn, monkeypatch):
    monkeypatch.setattr(agent, "propose_with_sources", lambda *args: pytest.fail("unexpected model call"))
    result = work_review.weekly_candidates(conn, date(2026, 11, 18))
    assert result["suggestions"] == []
    assert result["coverage"] == {"included": 0, "total": 0}


def test_structured_ai_candidate_cites_selected_event_without_saving(conn, monkeypatch):
    event = add_event(conn, "2026-11-18T10:00", "Recovered using a tested backup")
    def mock_cli(prompt, *, json_schema):
        assert "Recovered using a tested backup" in prompt
        assert "statements" in json_schema["properties"]
        return {"ok": True, "structured": {"statements": [
            {"text": "Verified backup recovery", "source_ids": [event["id"]]},
        ]}}

    monkeypatch.setattr(agent, "_run_cli", mock_cli)
    result = work_review.weekly_candidates(conn, date(2026, 11, 18))
    assert result["suggestions"] == [{"text": "Verified backup recovery", "source_ids": [event["id"]]}]
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 0
