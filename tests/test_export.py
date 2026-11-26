"""Tests for retrospective Markdown export."""
from __future__ import annotations

from datetime import UTC, date, datetime

from workledger.learning_models import LessonCreate
from workledger.schemas import AccomplishmentCreate, CaseCreate, EventCreate
from workledger.services import events, export, learning, retrospectives, work_items
from workledger.work_item_models import WorkItemCreate


def _seed(conn):
    source = events.create_event(conn, EventCreate(
        event_type="fix", occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        repo="org/repo", pr_number=42, summary="Fixed null check",
        evidence_url="https://github.com/org/repo/pull/42",
    ))
    retrospectives.create_accomplishment(conn, AccomplishmentCreate(
        title="Shipped search", occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        impact="Faster lookups", is_highlight=True, event_id=source["id"],
    ))
    retrospectives.create_case(conn, CaseCreate(
        title="Null pointer incident", occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
        phenomenon="Crash on empty input", root_cause="Missing guard", root_cause_confirmed=True,
        event_id=source["id"], evidence_url="https://github.com/org/repo/issues/7",
    ))
    return source


def _utc_for_local_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def test_lessons_and_use_history_are_filtered_by_local_periods(conn):
    source_event = events.create_event(conn, EventCreate(
        event_type="verification", occurred_at=datetime(2025, 10, 4, tzinfo=UTC),
        summary="Verified review evidence", evidence_url="https://example.test/source-pr",
    ))
    source_item = work_items.create_work_item(conn, WorkItemCreate(
        title="Source work", source_event_id=source_event["id"],
    ))
    target = work_items.create_work_item(conn, WorkItemCreate(title="Applied work"))
    seeds = [
        ("Monthly skill", "skill", "2026-05-01T00:05:00", "confirmed"),
        ("Quarterly process", "process", "2026-04-01T00:05:00", "confirmed"),
        ("Annual skill", "skill", "2026-01-01T00:05:00", "confirmed"),
        ("Older process", "process", "2025-10-04T12:30:00", "confirmed"),
        ("Draft only", "skill", "2026-05-05T12:30:00", "candidate"),
        ("Declined process", "process", "2026-05-05T12:30:00", "declined"),
    ]
    lesson_ids = {}
    for title, kind, stamp, status in seeds:
        lesson = learning.create_lesson(conn, LessonCreate(
            title=title, kind=kind, trigger="Input did not match", first_step="Verify the source",
            source_work_item_id=source_item["id"], source_event_id=source_event["id"],
            evidence_url="https://example.test/direct-proof",
        ))
        lesson_ids[title] = lesson["id"]
        if status != "candidate":
            learning.review_lesson(conn, lesson["id"], status)
        conn.execute("UPDATE lessons SET reviewed_at = ? WHERE id = ?", (_utc_for_local_time(stamp), lesson["id"]))
    conn.commit()

    stamped_outcomes = [
        ("applied", "2026-01-01T00:10:00", "Started in January"),
        ("did_not_help", "2026-04-01T00:10:00", "Checked a second case"),
        ("helped", "2026-05-01T00:10:00", "Verified the result in May"),
    ]
    for outcome, stamp, detail in stamped_outcomes:
        learning.record_lesson_use(
            conn, lesson_ids["Older process"], work_item_id=target["id"], outcome=outcome, detail=detail,
        )
        conn.execute("UPDATE lesson_use_history SET recorded_at = ? WHERE id = last_insert_rowid()",
                     (_utc_for_local_time(stamp),))
    conn.commit()

    today = date(2026, 5, 6)
    expected = [
        ("month", ["Monthly skill"], ["helped"]),
        ("quarter", ["Monthly skill", "Quarterly process"], ["helped", "did_not_help"]),
        ("year", ["Monthly skill", "Quarterly process", "Annual skill"], ["helped", "did_not_help", "applied"]),
        ("all", ["Monthly skill", "Quarterly process", "Annual skill", "Older process"],
         ["helped", "did_not_help", "applied"]),
    ]
    for period, lessons, outcomes in expected:
        page = export.retrospective_page(conn, period, today=today)
        assert [lesson["title"] for lesson in page["lessons"]] == lessons
        assert [entry["outcome"] for entry in page["lesson_uses"]] == outcomes
        assert page["totals"]["lessons"] == len(lessons)
        assert page["totals"]["lesson_uses"] == len(outcomes)

    month = export.export_markdown(conn, "month", today=today)
    assert "## Confirmed Skills & Process Lessons (1)" in month
    assert "## Lesson Applications & Outcomes (1)" in month
    assert "Verified the result in May" in month
    assert "Checked a second case" not in month
    assert "Draft only" not in month
    assert "Declined process" not in month
    assert f"/work-items/{target['id']}" in month
    assert f"/event/{source_event['id']}" in month
    assert "https://example.test/source-pr" in month
    assert "https://example.test/direct-proof" in month

    bounded, coverage = export.narrative_input(conn, "month", today=today)
    assert "Verified the result in May" in bounded
    assert coverage["included"]["lessons"] == coverage["included"]["lesson_uses"] == 1


def test_empty_learning_sections_do_not_reduce_small_model_input_budget(conn):
    _seed(conn)
    bounded, coverage = export.narrative_input(conn, "all", max_chars=460)
    assert "Accomplishments" in bounded
    assert "Confirmed Skills & Process Lessons" not in bounded
    assert "Lesson Applications & Outcomes" not in bounded
    assert coverage["totals"]["lessons"] == coverage["totals"]["lesson_uses"] == 0


class TestExport:
    def test_large_export_is_complete_and_model_coverage_is_bounded(self, conn):
        event_count = 502
        conn.executemany(
            'INSERT INTO work_events (event_type, occurred_at, source_key, summary) VALUES (?, ?, ?, ?)',
            [('fix', datetime.now().strftime('%Y-%m-%d 00:00:00'), f'fixture:{i}', f'Fixture #{i}')
             for i in range(event_count)],
        )
        md = export.export_markdown(conn, 'all')
        assert f'## Work Events ({event_count})' in md
        assert md.count('**fix**') == event_count

        bounded, coverage = export.narrative_input(conn, 'all', max_chars=600)
        assert len(bounded) <= 600
        assert coverage['totals']['events'] == event_count
        assert coverage['included']['events'] == bounded.count('**fix**')
        assert 0 < coverage['included']['events'] < event_count

    def test_markdown_structure(self, conn):
        source = _seed(conn)
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
        assert f"Source event: #{source['id']}" in md
        assert "https://github.com/org/repo/issues/7" in md

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
            event_type="manual", occurred_at=datetime(2020, 1, 1, tzinfo=UTC),
            summary="Old event",
        ))
        md = export.export_markdown(conn, "month")
        assert "Old event" not in md
