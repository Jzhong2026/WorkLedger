"""Retrospective export: structured Markdown (offline) + agent narrative (optional)."""
from __future__ import annotations

import sqlite3
from datetime import date

from . import events, retrospectives


def period_range(period: str) -> tuple[str, str]:
    today = date.today()
    if period == "month":
        date_from = today.replace(day=1).isoformat()
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_month, day=1).isoformat()
    elif period == "year":
        date_from = today.replace(month=1, day=1).isoformat()
    else:
        date_from = "1970-01-01"
    return date_from, today.isoformat()


def export_markdown(conn: sqlite3.Connection, period: str = "year") -> str:
    date_from, date_to = period_range(period)
    accs, _ = retrospectives.list_accomplishments(conn, date_from=date_from, date_to=date_to, page_size=500)
    cases, _ = retrospectives.list_cases(conn, date_from=date_from, date_to=date_to, page_size=500)
    evts, evt_total = events.search_events(conn, date_from=date_from, date_to=date_to, page_size=500)

    lines = [
        f"# WorkLedger Retrospective — {period}",
        f"\n_{date_from} → {date_to}_\n",
        f"\n## Accomplishments ({len(accs)})\n",
    ]
    if accs:
        for a in accs:
            star = " ⭐" if a["is_highlight"] else ""
            lines.append(f"\n### {a['title']}{star}")
            lines.append(f"- When: {a['occurred_at'][:10]}")
            if a["description"]:
                lines.append(f"- {a['description']}")
            if a["impact"]:
                lines.append(f"- Impact: {a['impact']}")
            if a["impact_evidence_url"]:
                lines.append(f"- Evidence: {a['impact_evidence_url']}")
            if a["tags"]:
                lines.append(f"- Tags: {a['tags']}")
    else:
        lines.append("\n_None recorded in this period._")

    lines.append(f"\n## Cases & Lessons ({len(cases)})\n")
    if cases:
        for c in cases:
            lines.append(f"\n### {c['title']}")
            lines.append(f"- When: {c['occurred_at'][:10]}")
            lines.append(f"- Phenomenon: {c['phenomenon']}")
            if c["root_cause"]:
                confirmed = "confirmed" if c["root_cause_confirmed"] else "unconfirmed"
                lines.append(f"- Root cause ({confirmed}): {c['root_cause']}")
            if c["solution"]:
                lines.append(f"- Solution: {c['solution']}")
            if c["verification"]:
                done = "verified" if c["verification_done"] else "pending verification"
                lines.append(f"- Verification ({done}): {c['verification']}")
    else:
        lines.append("\n_None recorded in this period._")

    lines.append(f"\n## Work Events ({evt_total})\n")
    if evts:
        for e in evts:
            pr = f" {e['repo']}#{e['pr_number']}" if e["repo"] else ""
            lines.append(f"- `{e['occurred_at'][:10]}` **{e['event_type']}**{pr} — {e['summary']}")
            if e["evidence_url"]:
                lines.append(f"  - Evidence: {e['evidence_url']}")
    else:
        lines.append("\n_None recorded in this period._")

    return "\n".join(lines) + "\n"