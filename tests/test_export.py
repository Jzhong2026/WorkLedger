"""Tests for retrospective Markdown export."""
from __future__ import annotations

from datetime import datetime, timezone

from workledger.schemas import AccomplishmentCreate, CaseCreate, EventCreate
from workledger.services import events, export, retrospectives


def _seed(conn):
    events.create_event(conn, EventCreate(
        event_type="fix", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        repo="org/repo", pr_number=42, summary="Fixed null check",
        evidence_url="https://github.com/org/repo/pull/42",
    ))
    retrospectives.create_accomplishment(conn, AccomplishmentCreate(
        title="Shipped search", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        impact="Faster lookups", is_highlight=True,
    ))
    retrospectives.create_case(conn, CaseCreate(
        title="Null pointer incident", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        phenomenon="Crash on empty input", root_cause="Missing guard", root_cause_confirmed=True,
    ))


class TestExport:
    def test_markdown_structure(self, conn):
        _seed(conn)
        md = export.export_markdown(conn, "year")
        assert "# WorkLedger Retrospective" in md
        assert "## Accomplishments (1)" in md
        assert "Shipped search" in md
        assert "⭐" in md  # highlight marker
        assert "## Cases & Lessons (1)" in md
        assert "Null pointer incident" in md
        assert "confirmed" in md
        assert "## Work Events" in md
        assert "https://github.com/org/repo/pull/42" in md

    def test_empty_period(self, conn):
        md = export.export_markdown(conn, "year")
        assert "None recorded" in md

    def test_period_range(self):
        f, t = export.period_range("month")
        assert f.endswith("-01")
        f2, _ = export.period_range("quarter")
        assert f2 <= t
        assert export.period_range("all")[0] == "1970-01-01"

    def test_month_filters_correctly(self, conn):
        events.create_event(conn, EventCreate(
            event_type="manual", occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            summary="Old event",
        ))
        md = export.export_markdown(conn, "month")
        assert "Old event" not in md