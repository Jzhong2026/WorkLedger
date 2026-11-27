from __future__ import annotations

from datetime import UTC, datetime

from workledger.schemas import EventCreate
from workledger.services import events, export, insights, work_review


def _seed(conn):
    now = datetime.now(UTC)
    for agent, summary in (("jira-import", "Jira snap"), ("jira-import", "Jira snap 2"),
                           ("bitbucket-sync", "PR anchor"), (None, "Human note")):
        events.create_event(conn, EventCreate(
            event_type="manual", occurred_at=now, summary=summary, source_agent=agent,
        ))


def test_insights_by_source_and_human_only_by_type(conn):
    _seed(conn)
    result = insights.get_insights(conn)
    by_source = {r["label"]: r["value"] for r in result["by_source"]}
    assert by_source == {"jira": 2, "bitbucket": 1, "human": 1}
    by_type = {r["label"]: r["value"] for r in result["by_type"]}
    assert by_type == {"manual": 1}  # 同步快照不再灌进 manual


def test_weekly_events_carry_source(conn):
    _seed(conn)
    result = work_review.weekly_review(conn)
    sources_by_summary = {e["summary"]: e["source"] for g in result["groups"] for e in g["events"]}
    assert sources_by_summary["Jira snap"] == "jira"
    assert sources_by_summary["PR anchor"] == "bitbucket"
    assert sources_by_summary["Human note"] == "human"


def test_export_events_subsections(conn):
    _seed(conn)
    md = export.export_markdown(conn, "all")
    assert "### Human records (1)" in md
    assert "### Jira snapshots (2)" in md
    assert "### Bitbucket PRs (1)" in md
    assert md.index("### Human records") < md.index("### Jira snapshots") < md.index("### Bitbucket PRs")


def test_export_empty_sources_omitted(conn):
    events.create_event(conn, EventCreate(event_type="manual", occurred_at=datetime.now(UTC), summary="Only human"))
    md = export.export_markdown(conn, "all")
    assert "### Human records (1)" in md
    assert "### Jira snapshots" not in md
    assert "### Bitbucket PRs" not in md


def test_narrative_input_stays_flat(conn):
    _seed(conn)
    md, coverage = export.narrative_input(conn, "all")
    assert "### Human records" not in md
    assert coverage["totals"]["events"] == 4
