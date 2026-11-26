"""Source-backed weekly reviews and read-only project briefings."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from .. import agent
from ..db import DatabaseError

# An event can be referenced by multiple handoffs. Choose a single reporting item
# inside the selected project so the contribution is counted once.
_ITEM_FOR_EVENT = """
    SELECT MIN(l.item_id) FROM work_item_events l JOIN work_items i ON i.id = l.item_id
    WHERE l.event_id = e.id AND (:project IS NULL OR i.project_id = :project)
"""


def weekly_review(
    conn: sqlite3.Connection, day: date | None = None, project_id: int | None = None,
) -> dict:
    conn.execute("SAVEPOINT weekly_review")
    try:
        return _weekly_snapshot(conn, day or date.today(), project_id)
    finally:
        conn.execute("RELEASE weekly_review")


def _weekly_snapshot(conn: sqlite3.Connection, day: date, project_id: int | None) -> dict:
    start = day - timedelta(days=day.weekday())
    stop = start + timedelta(days=7)
    params = {"start": start.isoformat(), "stop": stop.isoformat(), "project": project_id}
    rows = conn.execute(f"""
        SELECT e.id, e.summary, e.event_type, e.occurred_at, e.repo, e.pr_number,
               e.jira_key, e.source_agent, e.evidence_url, e.verification_done,
               e.verification_result, p.jira_key AS parent_key,
               i.id AS item_id, i.title AS item_title, h.actor AS actor
        FROM work_events e
        LEFT JOIN work_events p ON p.id = e.parent_event_id
        LEFT JOIN work_items i ON i.id = ({_ITEM_FOR_EVENT})
        LEFT JOIN work_item_handoffs h ON h.event_id = e.id AND h.item_id = i.id
        WHERE e.occurred_at >= :start AND e.occurred_at < :stop
          AND (:project IS NULL OR i.id IS NOT NULL OR e.project_id = :project)
        ORDER BY e.occurred_at DESC, e.id DESC
    """, params)
    groups: dict[tuple, dict] = {}
    for row in rows:
        if row["item_id"]:
            key, title = ("item", row["item_id"]), row["item_title"]
        elif row["parent_key"] or row["jira_key"]:
            issue = row["parent_key"] or row["jira_key"]
            key, title = ("jira", issue), issue
        elif row["repo"] and row["pr_number"] is not None:
            key = ("pr", row["repo"], row["pr_number"])
            title = f"{row['repo']}#{row['pr_number']}"
        else:
            key, title = ("event", row["id"]), row["summary"] or f"Event #{row['id']}"
        group = groups.setdefault(key, {"title": title, "item_id": row["item_id"], "events": []})
        group["events"].append(dict(row))

    reviewed = {}
    for table in ("accomplishments", "cases"):
        entries = conn.execute(f"""
            SELECT r.* FROM {table} r
            LEFT JOIN work_events e ON e.id = r.event_id
            WHERE r.occurred_at >= :start AND r.occurred_at < :stop
              AND (:project IS NULL OR e.project_id = :project OR ({_ITEM_FOR_EVENT}) IS NOT NULL)
            ORDER BY r.occurred_at DESC, r.id DESC
        """, params)
        reviewed[table] = [dict(row) for row in entries]
    lessons = conn.execute("""
        SELECT l.id, l.kind, l.title, l."trigger", l.first_step, l.limits,
               l.source_work_item_id, l.source_event_id, i.title AS item_title
        FROM lessons l JOIN work_items i ON i.id = l.source_work_item_id
        WHERE l.status = 'confirmed' AND datetime(l.reviewed_at, 'localtime') >= :start
          AND datetime(l.reviewed_at, 'localtime') < :stop
          AND (:project IS NULL OR i.project_id = :project)
        ORDER BY l.reviewed_at DESC, l.id DESC
    """, params)
    uses = conn.execute("""
        SELECT u.id, u.lesson_id, l.title, u.work_item_id, i.title AS item_title,
               u.outcome, u.detail, u.recorded_at
        FROM lesson_use_history u JOIN lessons l ON l.id = u.lesson_id
        JOIN work_items i ON i.id = u.work_item_id
        WHERE datetime(u.recorded_at, 'localtime') >= :start AND datetime(u.recorded_at, 'localtime') < :stop
          AND (:project IS NULL OR i.project_id = :project)
        ORDER BY u.recorded_at DESC, u.id DESC
    """, params)
    return {"start": start.isoformat(), "end": (stop - timedelta(days=1)).isoformat(),
            "groups": list(groups.values()), "reuse": [dict(row) for row in uses],
            "lessons": [dict(row) for row in lessons], **reviewed}


def _grounded_suggestions(records: list[dict], task: str) -> dict:
    # Preserve complete source IDs and disclose how many records fit in the model input.
    chosen = []
    budget = 6800
    for record in records:
        entry = {key: value[:260] if isinstance(value, str) else value for key, value in record.items()}
        size = len(json.dumps(entry, ensure_ascii=False).encode("utf-16-le")) // 2
        if size > budget:
            break
        chosen.append(entry)
        budget -= size + 2
    result = {"suggestions": [], "coverage": {"included": len(chosen), "total": len(records)}}
    if not chosen:
        return result
    allowed = {row["id"] for row in chosen}
    suggestions = agent.propose_with_sources(task, chosen)
    for suggestion in suggestions:
        if not suggestion["source_ids"] or not set(suggestion["source_ids"]) <= allowed:
            raise DatabaseError("CodeBuddy returned a suggestion without valid source records. Retry.", status_code=502)
    result["suggestions"] = suggestions
    return result


def weekly_candidates(conn, day: date | None = None, project_id: int | None = None) -> dict:
    report = weekly_review(conn, day, project_id)
    records = [
        {"id": event["id"], "work_item": group["title"], "summary": event["summary"],
         "type": event["event_type"], "verified": bool(event["verification_done"]),
         "verification": event["verification_result"], "recorded_by": event["source_agent"],
         "actor": event["actor"]}
        for group in report["groups"] for event in group["events"]
    ]
    return _grounded_suggestions(records, (
        "Propose up to five weekly highlights, lessons or process improvements. Group related work. "
        "Describe the contribution and supported outcome. Mention which evidence of impact is missing. "
        "Imported Jira descriptions represent requirements, not completed personal contributions."
    ))


def project_briefing(conn, project_id: int | None = None, question: str | None = None) -> dict:
    records = [dict(row) for row in conn.execute("""
        SELECT id, title, goal, stage, owner, last_verified_result, blocker, next_step,
               needs_decision, followup_date, updated_at, (
                   SELECT summary FROM work_item_handoffs h
                   WHERE h.item_id = work_items.id ORDER BY version DESC LIMIT 1
               ) AS latest_handoff FROM work_items
        WHERE (? IS NULL OR project_id = ?)
        ORDER BY CASE WHEN stage = 'done' THEN 1 ELSE 0 END, needs_decision DESC, updated_at DESC, id DESC
    """, (project_id, project_id))]
    result = _grounded_suggestions(records, (
        "Answer this project progress question using the supplied item snapshots. Identify owners, "
        "verified results, blockers, decisions and next steps when relevant. A missing verification "
        f"is unknown. Today is {date.today().isoformat()}. Do not infer a percentage. Question: "
        + (question or "What needs attention?")
    ))
    by_id = {row["id"]: row["title"] for row in records}
    citations = dict.fromkeys(i for s in result["suggestions"] for i in s["source_ids"])
    lines = [s["text"] + " [" + ", ".join(f"#{i}" for i in s["source_ids"]) + "]" for s in result["suggestions"]]
    return {"text": "\n\n".join(lines) if lines else "No recorded work items support an answer.",
            "sources": [{"item_id": i, "title": by_id[i]} for i in citations], "coverage": result["coverage"]}
