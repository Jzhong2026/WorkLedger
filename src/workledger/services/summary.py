"""Assistant-facing project summary with explicit freshness."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta

from ..config import settings
from . import jira_import, sources, sync_state


def parse_window(window: str) -> int:
    match = re.fullmatch(r"(\d+)d", window.strip())
    if not match or not 1 <= int(match.group(1)) <= 90:
        raise ValueError("Window must look like '7d' (1-90 days).")
    return int(match.group(1))


def _ticket(row: sqlite3.Row, item_ids: dict) -> dict:
    extra = json.loads(row["extra_json"] or "{}")
    return {
        "key": row["jira_key"], "summary": row["summary"],
        "status": extra.get("status"), "assignee": extra.get("assignee_name"),
        "updated": extra.get("jira_updated"), "url": extra.get("jira_url"),
        "work_item_id": item_ids.get(row["jira_key"]),
        "done": jira_import.is_done(extra.get("status_category"), extra.get("status")),
    }


def project_summary(conn: sqlite3.Connection, key: str, window: str = "7d", scope: str = "all") -> dict:
    if scope not in ("all", "mine"):
        raise ValueError("Scope must be 'all' or 'mine'.")
    days = parse_window(window)
    project = conn.execute("SELECT * FROM projects WHERE key=?", (key.strip().upper(),)).fetchone()
    if project is None:
        raise KeyError(f"Project {key.strip().upper()} not found")
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    today_iso = today.isoformat()

    item_ids = {
        row["jira_key"]: row["id"]
        for row in conn.execute(
            "SELECT id, jira_key FROM work_items WHERE jira_key IS NOT NULL AND project_id=?",
            (project["id"],),
        )
    }
    states = sync_state.get_states(conn)
    account_id, my_uuid = sources.my_identities(conn)
    ticket_rows = conn.execute(
        "SELECT jira_key, summary, extra_json FROM work_events "
        "WHERE source_agent='jira-import' AND jira_key IS NOT NULL AND project_id=? ORDER BY jira_key",
        (project["id"],),
    ).fetchall()
    if scope == "mine":
        ticket_rows = [r for r in ticket_rows
                       if account_id is not None
                       and json.loads(r["extra_json"] or "{}").get("assignee_account_id") == account_id]
    tickets = [_ticket(row, item_ids) for row in ticket_rows]
    by_status: dict[str, int] = {}
    for ticket in tickets:
        name = ticket["status"] or "?"
        by_status[name] = by_status.get(name, 0) + 1
    open_tickets = [t for t in tickets if not t["done"]]
    changed = [t for t in tickets if t["updated"] and start <= t["updated"][:10] <= today_iso]

    prs = []
    if key.strip().upper() == settings.sync_bitbucket_project.upper():
        repos = [f"{settings.sync_bitbucket_workspace}/{r.strip()}" for r in settings.sync_bitbucket_repos.split(",") if r.strip()]
        placeholders = ", ".join("?" for _ in repos)
        for row in conn.execute(
            f"SELECT repo, pr_number, summary, extra_json FROM work_events "
            f"WHERE source_agent='bitbucket-sync' AND event_type='pr_created' AND repo IN ({placeholders})",
            repos,
        ):
            extra = json.loads(row["extra_json"] or "{}")
            state = extra.get("state")
            updated = (extra.get("bitbucket_updated") or "")[:10]
            if state != "OPEN" and not (start <= updated <= today_iso):
                continue
            reviewers = extra.get("reviewers") or []
            mine_review = next(
                (r for r in reviewers if my_uuid is not None and r.get("uuid") == my_uuid), None
            )
            prs.append({
                "repo": row["repo"], "pr_number": row["pr_number"], "title": row["summary"],
                "state": state, "author": extra.get("author"), "reviewers": reviewers,
                "updated_on": extra.get("bitbucket_updated"), "url": extra.get("url"),
                "jira_keys": extra.get("jira_keys") or [],
                "mine": {
                    "authored": my_uuid is not None and extra.get("author_uuid") == my_uuid,
                    "reviewing": mine_review is not None,
                    "needs_my_review": state == "OPEN" and mine_review is not None and not mine_review.get("approved"),
                },
            })
    if scope == "mine":
        prs = [p for p in prs if p["mine"]["authored"] or p["mine"]["reviewing"]]
    pr_counts = {
        "open": sum(1 for p in prs if p["state"] == "OPEN"),
        "merged": sum(1 for p in prs if p["state"] == "MERGED"),
        "needs_review": sum(1 for p in prs if p["mine"]["needs_my_review"]),
    }

    overdue = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.due_date, t.status, p.key AS project_key FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "LEFT JOIN projects p ON p.id = COALESCE(t.project_id, e.project_id) "
        "WHERE t.status != 'done' AND t.due_date IS NOT NULL AND t.due_date < ? ORDER BY t.due_date",
        (today_iso,),
    )]
    project_open = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.status, t.due_date, t.next_followup FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "WHERE COALESCE(t.project_id, e.project_id) = ? AND t.status != 'done' ORDER BY t.due_date",
        (project["id"],),
    )]
    due_today = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.status, t.due_date FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "WHERE COALESCE(t.project_id, e.project_id) = ? AND t.status != 'done' AND t.due_date=?",
        (project["id"], today_iso),
    )]
    items = [dict(r) for r in conn.execute(
        "SELECT id, title, stage, jira_key, next_step, followup_date, needs_decision FROM work_items "
        "WHERE project_id=? AND stage != 'done' ORDER BY needs_decision DESC, updated_at DESC",
        (project["id"],),
    )]
    return {
        "project": {"id": project["id"], "key": project["key"], "name": project["name"]},
        "window": {"days": days, "from": start, "to": today_iso},
        "scope": scope,
        "generated_at": sync_state.utc_now_iso(),
        "tickets": {
            "counts": {"open": len(open_tickets), "done": len(tickets) - len(open_tickets), "by_status": by_status},
            "open": open_tickets, "changed_in_window": changed,
        },
        "prs": {"counts": pr_counts, "items": prs},
        "todos": {"overdue_global": overdue, "project_open": project_open, "due_today": due_today},
        "work_items": {
            "open": len(items), "needs_decision": sum(1 for i in items if i["needs_decision"]), "items": items,
        },
        "sync": {
            source: {**state, "stale": sync_state.is_stale(state, settings.sync_interval_minutes)}
            for source, state in states.items()
        },
    }
