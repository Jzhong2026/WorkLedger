"""Offline retrospective export and bounded model input."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Literal

from . import events, retrospectives

Period = Literal["month", "quarter", "year", "all"]
_PAGE_SIZE = 100
# Keep the model prompt usable by the CLI's Windows launcher.
_NARRATIVE_CHARS = 6_000
_SECTIONS = (
    ("accomplishments", "Accomplishments", retrospectives.list_accomplishments),
    ("cases", "Cases & Lessons", retrospectives.list_cases),
    ("events", "Work Events", events.search_events),
)


def period_range(period: str, *, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    if period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    elif period == "year":
        start = today.replace(month=1, day=1)
    elif period == "all":
        start = date(1970, 1, 1)
    else:
        raise ValueError("Period must be month, quarter, year, or all.")
    return start.isoformat(), today.isoformat()


def retrospective_page(
    conn: sqlite3.Connection, period: str = "year", *, page: int = 1, page_size: int = _PAGE_SIZE,
) -> dict:
    if page < 1 or not 1 <= page_size <= _PAGE_SIZE:
        raise ValueError(f"Page must be positive and page size must be between 1 and {_PAGE_SIZE}.")
    date_from, date_to = period_range(period)
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


def _render_record(conn: sqlite3.Connection, key: str, record: dict) -> str:
    if key == "accomplishments":
        return "\n".join(_accomplishment_lines(conn, record))
    if key == "cases":
        return "\n".join(_case_lines(conn, record))
    return "\n".join(_event_lines(record))


def _render_export(
    conn: sqlite3.Connection, period: str, *, max_chars: int | None = None, today: date | None = None,
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
        first_pages = [fetch(conn, **window) for _, _, fetch in _SECTIONS]
        if max_chars is not None:
            # Allow for the longest possible section headings and empty-state messages.
            overhead = len(title) + 1 + sum(
                len(f"\n\n## {heading} ({total} of {total} included)\n\n_None recorded in this period._")
                for (_, heading, _), (_, total) in zip(_SECTIONS, first_pages, strict=True)
            )
            if max_chars < overhead:
                raise ValueError("Model input budget is too small to describe the retrospective.")
            budget = max_chars - overhead
        for (key, heading, fetch), (rows, total) in zip(_SECTIONS, first_pages, strict=True):
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
                rows, _ = fetch(conn, page=page, **window)
            included[key] = len(blocks)
            totals[key] = total
            count = str(total) if len(blocks) == total else f"{len(blocks)} of {total} included"
            parts.append(f"## {heading} ({count})")
            if blocks:
                parts.append("\n\n".join(blocks))
            else:
                parts.append("_No records included._" if total else "_None recorded in this period._")
    finally:
        conn.execute("RELEASE retrospective_export")
    return "\n\n".join(parts) + "\n", {"included": included, "totals": totals}


def export_markdown(conn: sqlite3.Connection, period: str = "year") -> str:
    markdown, _ = _render_export(conn, period)
    return markdown


def narrative_input(
    conn: sqlite3.Connection,
    period: str = "year",
    *,
    max_chars: int = _NARRATIVE_CHARS,
    today: date | None = None,
) -> tuple[str, dict]:
    """Return complete records within the model budget and the exact section coverage."""
    markdown, coverage = _render_export(conn, period, max_chars=max_chars, today=today)
    if not any(coverage["totals"].values()):
        raise ValueError("There are no records in this period.")
    if not any(coverage["included"].values()):
        raise ValueError("The records exceed the model input budget. Export Markdown for the complete records.")
    return markdown, coverage
