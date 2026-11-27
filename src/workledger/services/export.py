"""Offline retrospective export and bounded model input."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Literal

from ..config import settings
from . import events, retrospectives

Period = Literal["week", "month", "quarter", "year", "all"]
_PAGE_SIZE = 100
# Keep the model prompt usable by the CLI's Windows launcher.
_NARRATIVE_CHARS = 6_000
_LEARNING_KEYS = {"lessons", "lesson_uses"}
_LESSON_SOURCE = """
    l.source_work_item_id, source.title AS source_work_item_title,
    l.source_event_id, e.summary AS source_event_summary,
    e.evidence_url AS source_event_url, l.evidence_url
"""
_LEARNING_JOINS = """
    JOIN work_items source ON source.id = l.source_work_item_id
    LEFT JOIN work_events e ON e.id = l.source_event_id
"""


def _learning_page(
    conn: sqlite3.Connection, query: str, *, date_from: str, date_to: str,
    page: int, page_size: int,
) -> tuple[list[dict], int]:
    params = (date_from, date_to)
    total = conn.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
    rows = conn.execute(
        f"{query} ORDER BY period_at DESC, id DESC LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size),
    )
    return [dict(row) for row in rows], total


def _confirmed_lessons(
    conn: sqlite3.Connection, *, date_from: str, date_to: str, page: int = 1, page_size: int = _PAGE_SIZE,
) -> tuple[list[dict], int]:
    query = f"""
        SELECT l.id AS id, l.title, l.kind, l."trigger", l.first_step, l.limits, l.tags,
               l.reviewed_at AS period_at, date(l.reviewed_at, 'localtime') AS reviewed_on, {_LESSON_SOURCE}
        FROM lessons l {_LEARNING_JOINS}
        WHERE l.status = 'confirmed' AND date(l.reviewed_at, 'localtime') BETWEEN ? AND ?
    """
    rows, total = _learning_page(
        conn, query, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )
    for row in rows:
        row["tags"] = json.loads(row["tags"])
        row.pop("period_at")
    return rows, total


def _lesson_applications(
    conn: sqlite3.Connection, *, date_from: str, date_to: str, page: int = 1, page_size: int = _PAGE_SIZE,
) -> tuple[list[dict], int]:
    query = f"""
        SELECT use.id AS id, use.lesson_id, l.title, use.outcome, use.detail, use.work_item_id,
               applied.title AS work_item_title, use.recorded_at AS period_at,
               date(use.recorded_at, 'localtime') AS recorded_on, {_LESSON_SOURCE}
        FROM lesson_use_history use
        JOIN lessons l ON l.id = use.lesson_id
        JOIN work_items applied ON applied.id = use.work_item_id
        {_LEARNING_JOINS}
        WHERE date(use.recorded_at, 'localtime') BETWEEN ? AND ?
    """
    rows, total = _learning_page(
        conn, query, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )
    for row in rows:
        row.pop("period_at")
    return rows, total


_SECTIONS = (
    ("accomplishments", "Accomplishments", retrospectives.list_accomplishments),
    ("cases", "Cases & Lessons", retrospectives.list_cases),
    ("lessons", "Confirmed Skills & Process Lessons", _confirmed_lessons),
    ("lesson_uses", "Lesson Applications & Outcomes", _lesson_applications),
    ("events", "Work Events", events.search_events),
)


def period_range(period: str, *, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    elif period == "year":
        start = today.replace(month=1, day=1)
    elif period == "all":
        start = date(1970, 1, 1)
    else:
        raise ValueError("Period must be week, month, quarter, year, or all.")
    return start.isoformat(), today.isoformat()


def retrospective_page(
    conn: sqlite3.Connection, period: str = "year", *,
    page: int = 1, page_size: int = _PAGE_SIZE, today: date | None = None,
) -> dict:
    if page < 1 or not 1 <= page_size <= _PAGE_SIZE:
        raise ValueError(f"Page must be positive and page size must be between 1 and {_PAGE_SIZE}.")
    date_from, date_to = period_range(period, today=today)
    window = {"date_from": date_from, "date_to": date_to, "page": page, "page_size": page_size}
    items = {}
    totals = {}
    for key, _, fetch in _SECTIONS:
        items[key], totals[key] = fetch(conn, **window)
    return {
        "period": period, "date_from": date_from, "date_to": date_to,
        **items, "totals": totals, "page": page, "page_size": page_size,
        "pages": (max(totals.values()) + page_size - 1) // page_size,
    }


def _source_lines(conn: sqlite3.Connection, record: dict, evidence_url: str | None) -> list[str]:
    event_id = record.get("event_id")
    if event_id is None:
        return []
    source = events.get_event(conn, event_id)
    if not source:
        return []
    lines = [f"- Source event: #{event_id} — {source['summary']}"]
    if source["evidence_url"] and source["evidence_url"] != evidence_url:
        lines.append(f"- Source evidence: {source['evidence_url']}")
    return lines


def _accomplishment_lines(conn: sqlite3.Connection, item: dict) -> list[str]:
    star = " ⭐" if item["is_highlight"] else ""
    lines = [f"### {item['title']}{star}", f"- When: {item['occurred_at'][:10]}"]
    if item["description"]:
        lines.append(f"- {item['description']}")
    if item["impact"]:
        lines.append(f"- Impact: {item['impact']}")
    if item["impact_evidence_url"]:
        lines.append(f"- Evidence: {item['impact_evidence_url']}")
    if item["tags"]:
        lines.append(f"- Tags: {item['tags']}")
    lines.extend(_source_lines(conn, item, item["impact_evidence_url"]))
    return lines


def _case_lines(conn: sqlite3.Connection, item: dict) -> list[str]:
    lines = [
        f"### {item['title']}",
        f"- When: {item['occurred_at'][:10]}",
        f"- Phenomenon: {item['phenomenon']}",
    ]
    if item["root_cause"]:
        status = "confirmed" if item["root_cause_confirmed"] else "unconfirmed"
        lines.append(f"- Root cause ({status}): {item['root_cause']}")
    if item["solution"]:
        lines.append(f"- Solution: {item['solution']}")
    if item["verification"]:
        status = "verified" if item["verification_done"] else "pending verification"
        lines.append(f"- Verification ({status}): {item['verification']}")
    if evidence_url := item.get("evidence_url"):
        lines.append(f"- Evidence: {evidence_url}")
    if item["tags"]:
        lines.append(f"- Tags: {item['tags']}")
    lines.extend(_source_lines(conn, item, evidence_url))
    return lines


def _event_lines(item: dict) -> list[str]:
    labels = [f"#{item['id']}"]
    if item["repo"]:
        labels.append(item["repo"] + (f"#{item['pr_number']}" if item["pr_number"] else ""))
    if item["jira_key"]:
        labels.append(item["jira_key"])
    reference = " · ".join(labels)
    lines = [f"- `{item['occurred_at'][:10]}` **{item['event_type']}** {reference} — {item['summary']}"]
    if item["evidence_url"]:
        lines.append(f"  - Evidence: {item['evidence_url']}")
    if item["root_cause"]:
        status = "confirmed" if item["root_cause_confirmed"] else "unconfirmed"
        lines.append(f"  - Root cause ({status}): {item['root_cause']}")
    if item["verification_result"]:
        status = "verified" if item["verification_done"] else "pending verification"
        lines.append(f"  - Verification ({status}): {item['verification_result']}")
    return lines


def _workspace_link(path: str, label: str) -> str:
    host = settings.workledger_host
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"[{label}](http://{host}:{settings.workledger_port}{path})"


def _lesson_source_lines(item: dict) -> list[str]:
    work_item_id = item["source_work_item_id"]
    work_item = _workspace_link(f"/work-items/{work_item_id}", f"#{work_item_id}")
    lines = [f"- Source work item: {work_item} — {item['source_work_item_title']}"]
    if event_id := item["source_event_id"]:
        event_link = _workspace_link(f"/event/{event_id}", f"#{event_id}")
        summary = f" — {item['source_event_summary']}" if item["source_event_summary"] else ""
        lines.append(f"- Source event: {event_link}{summary}")
    if evidence_url := item["evidence_url"]:
        lines.append(f"- Evidence: <{evidence_url}>")
    if item["source_event_url"] and item["source_event_url"] != evidence_url:
        lines.append(f"- Source evidence: <{item['source_event_url']}>")
    return lines


def _lesson_lines(item: dict) -> list[str]:
    kind = "Skill" if item["kind"] == "skill" else "Process improvement"
    lesson_link = _workspace_link(f"/learning?lesson_id={item['id']}", f"Lesson #{item['id']}")
    lines = [
        f"### {item['title']}", f"- {kind} · Confirmed {item['reviewed_on']} · {lesson_link}",
        f"- Trigger: {item['trigger']}", f"- First step: {item['first_step']}",
    ]
    if item["limits"]:
        lines.append(f"- Limits: {item['limits']}")
    if item["tags"]:
        lines.append(f"- Tags: {', '.join(item['tags'])}")
    return [*lines, *_lesson_source_lines(item)]


def _lesson_use_lines(item: dict) -> list[str]:
    outcome = {"applied": "Applied", "helped": "Helped", "did_not_help": "Did not help"}[item["outcome"]]
    work_item_id = item["work_item_id"]
    application = _workspace_link(f"/work-items/{work_item_id}", f"#{work_item_id}")
    lesson_id = item["lesson_id"]
    lesson = _workspace_link(
        f"/learning?lesson_id={lesson_id}&work_item_id={work_item_id}", f"Lesson #{lesson_id}",
    )
    lines = [
        f"### {item['title']} · {outcome}", f"- Recorded: {item['recorded_on']} · {lesson}",
        f"- Applied in: {application} — {item['work_item_title']}",
    ]
    if item["detail"]:
        lines.append(f"- Observation: {item['detail']}")
    return [*lines, *_lesson_source_lines(item)]


def _render_record(conn: sqlite3.Connection, key: str, record: dict) -> str:
    if key == "accomplishments":
        return "\n".join(_accomplishment_lines(conn, record))
    if key == "cases":
        return "\n".join(_case_lines(conn, record))
    if key == "lessons":
        return "\n".join(_lesson_lines(record))
    if key == "lesson_uses":
        return "\n".join(_lesson_use_lines(record))
    return "\n".join(_event_lines(record))


def _render_export(
    conn: sqlite3.Connection, period: str, *, max_chars: int | None = None, today: date | None = None,
    scope: str = "all",
) -> tuple[str, dict]:
    date_from, date_to = period_range(period, today=today)
    title = f"# WorkLedger Retrospective — {period}\n\n_{date_from} → {date_to}_"
    totals = {}
    included = {}
    parts = [title]
    window = {"date_from": date_from, "date_to": date_to, "page_size": _PAGE_SIZE}

    # A read snapshot keeps totals and all later pages consistent with the first page.
    conn.execute("SAVEPOINT retrospective_export")
    try:
        first_pages = [fetch(conn, **({**window, "scope": scope} if key == "events" else window))
                       for key, _, fetch in _SECTIONS]
        sections = zip(_SECTIONS, first_pages, strict=True)
        rendered = []
        for (key, heading, fetch), (rows, total) in sections:
            totals[key] = total
            included[key] = 0
            if max_chars is not None and key in _LEARNING_KEYS and not total:
                continue
            rendered.append((key, heading, fetch, rows, total))
        if max_chars is not None:
            # Allow for the longest possible section headings and empty-state messages.
            overhead = len(title) + 1 + sum(
                len(f"\n\n## {heading} ({total} of {total} included)\n\n_None recorded in this period._")
                for _, heading, _, _, total in rendered
            )
            if max_chars < overhead:
                raise ValueError("Model input budget is too small to describe the retrospective.")
            budget = max_chars - overhead
        for key, heading, fetch, rows, total in rendered:
            blocks = []
            page = 1
            while rows:
                for record in rows:
                    block = _render_record(conn, key, record)
                    if max_chars is None:
                        blocks.append(block)
                    elif len(block) + 2 <= budget:
                        blocks.append(block)
                        budget -= len(block) + 2
                if page * _PAGE_SIZE >= total or (max_chars is not None and budget < 32):
                    break
                page += 1
                rows, _ = fetch(conn, page=page, **({**window, "scope": scope} if key == "events" else window))
            included[key] = len(blocks)
            count = str(total) if len(blocks) == total else f"{len(blocks)} of {total} included"
            parts.append(f"## {heading} ({count})")
            if blocks:
                parts.append("\n\n".join(blocks))
            else:
                parts.append("_No records included._" if total else "_None recorded in this period._")
    finally:
        conn.execute("RELEASE retrospective_export")
    return "\n\n".join(parts) + "\n", {"included": included, "totals": totals}


def export_markdown(
    conn: sqlite3.Connection, period: str = "year", *, today: date | None = None, scope: str = "all",
) -> str:
    markdown, _ = _render_export(conn, period, today=today, scope=scope)
    return markdown


def narrative_input(
    conn: sqlite3.Connection,
    period: str = "year",
    *,
    max_chars: int = _NARRATIVE_CHARS,
    today: date | None = None,
    scope: str = "all",
) -> tuple[str, dict]:
    """Return complete records within the model budget and the exact section coverage."""
    markdown, coverage = _render_export(conn, period, max_chars=max_chars, today=today, scope=scope)
    if not any(coverage["totals"].values()):
        raise ValueError("There are no records in this period.")
    if not any(coverage["included"].values()):
        raise ValueError("The records exceed the model input budget. Export Markdown for the complete records.")
    return markdown, coverage
