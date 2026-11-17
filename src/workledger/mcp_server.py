"""MCP server exposing WorkLedger tools for external agents."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from mcp.server.mcpserver import MCPServer

from .config import settings
from .db import DatabaseError, get_connection, init_db
from .schemas import EventCreate, EventUpdate, TodoCreate, TodoUpdate
from .services import events, retrospectives, todos

mcp = MCPServer("WorkLedger", instructions="Record, search, and follow up on work events. All writes are deduplicated by source_key.")


def _conn():
    init_db(settings.db_path)
    return get_connection(settings.db_path)


def _err(e: Exception) -> str:
    if isinstance(e, DatabaseError):
        return json.dumps({"error": str(e), "retryable": e.retryable})
    return json.dumps({"error": str(e)})


@mcp.tool()
def record_event(
    event_type: str,
    occurred_at: str,
    summary: str,
    repo: str | None = None,
    pr_number: int | None = None,
    comment_id: str | None = None,
    jira_key: str | None = None,
    source_key: str | None = None,
    source_agent: str | None = None,
    detail: str | None = None,
    evidence_url: str | None = None,
    root_cause: str | None = None,
    root_cause_confirmed: bool = False,
    verification_result: str | None = None,
    verification_done: bool = False,
    reply_status: str | None = None,
) -> str:
    """Record a work event. Deduplicates by source_key (auto-generated from type+repo+PR+comment if omitted).
    event_type: pr_created|review_finding|comment_analysis|fix|verification|reply_drafted|reply_published|manual
    occurred_at: ISO datetime string. reply_status: draft|published (for reply events)."""
    try:
        data = EventCreate(
            event_type=event_type,
            occurred_at=datetime.fromisoformat(occurred_at),
            summary=summary, repo=repo, pr_number=pr_number, comment_id=comment_id,
            jira_key=jira_key, source_key=source_key, source_agent=source_agent,
            detail=detail, evidence_url=evidence_url, root_cause=root_cause,
            root_cause_confirmed=root_cause_confirmed,
            verification_result=verification_result, verification_done=verification_done,
            reply_status=reply_status,
        )
        result = events.create_event(_conn(), data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def update_event(
    event_id: int,
    summary: str | None = None,
    detail: str | None = None,
    evidence_url: str | None = None,
    root_cause: str | None = None,
    root_cause_confirmed: bool | None = None,
    verification_result: str | None = None,
    verification_done: bool | None = None,
    reply_status: str | None = None,
) -> str:
    """Update an existing work event by ID. Only provided fields are changed. Sets user_edited flag."""
    try:
        data = EventUpdate(
            summary=summary, detail=detail, evidence_url=evidence_url,
            root_cause=root_cause, root_cause_confirmed=root_cause_confirmed,
            verification_result=verification_result, verification_done=verification_done,
            reply_status=reply_status,
        )
        result = events.update_event(_conn(), event_id, data, changed_by="mcp_agent")
        if not result:
            return json.dumps({"error": f"Event {event_id} not found"})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def search_events(
    q: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    jira_key: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Search work events by keyword (Chinese/English), repo, PR, Jira, type, date range. Returns paginated results."""
    try:
        items, total = events.search_events(
            _conn(), q=q, repo=repo, pr_number=pr_number, jira_key=jira_key,
            event_type=event_type, date_from=date_from, date_to=date_to,
            page=page, page_size=page_size,
        )
        pages = (total + page_size - 1) // page_size if total else 0
        return json.dumps({"items": items, "total": total, "page": page, "pages": pages}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_event_detail(event_id: int) -> str:
    """Get full detail of a work event including evidence links, root cause, and verification."""
    try:
        result = events.get_event(_conn(), event_id)
        if not result:
            return json.dumps({"error": f"Event {event_id} not found"})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_pr_timeline(repo: str, pr_number: int) -> str:
    """Get all events for a specific PR in chronological order."""
    try:
        result = events.get_pr_timeline(_conn(), repo, pr_number)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_todo(
    title: str,
    description: str | None = None,
    status: str = "pending",
    event_id: int | None = None,
    wait_target: str | None = None,
    due_date: str | None = None,
    next_followup: str | None = None,
    source_key: str | None = None,
) -> str:
    """Create a to-do/follow-up. status: pending|waiting|done. Optionally link to an event. Deduplicates by source_key."""
    try:
        data = TodoCreate(
            title=title, description=description, status=status,
            event_id=event_id, wait_target=wait_target,
            due_date=due_date, next_followup=next_followup, source_key=source_key,
        )
        result = todos.create_todo(_conn(), data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def update_todo(
    todo_id: int,
    title: str | None = None,
    status: str | None = None,
    wait_target: str | None = None,
    due_date: str | None = None,
    next_followup: str | None = None,
) -> str:
    """Update a to-do. status: pending|waiting|done. Setting done records completed_at; reopening clears it."""
    try:
        data = TodoUpdate(
            title=title, status=status, wait_target=wait_target,
            due_date=due_date, next_followup=next_followup,
        )
        result = todos.update_todo(_conn(), todo_id, data)
        if not result:
            return json.dumps({"error": f"Todo {todo_id} not found"})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_todos(status: str | None = None, page: int = 1) -> str:
    """List to-dos, optionally filtered by status (pending|waiting|done)."""
    try:
        items, total = todos.list_todos(_conn(), status=status, page=page)
        return json.dumps({"items": items, "total": total, "page": page}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def today_followups() -> str:
    """Get to-dos needing attention today: due, follow-up date reached, or no date set."""
    try:
        today = date.today().isoformat()
        items = todos.today_todos(_conn(), today)
        return json.dumps({"today": today, "items": items}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def record_accomplishment(
    title: str,
    occurred_at: str,
    description: str | None = None,
    impact: str | None = None,
    impact_evidence_url: str | None = None,
    is_highlight: bool = False,
    tags: str | None = None,
    source_key: str | None = None,
) -> str:
    """Record an accomplishment for retrospectives. occurred_at: ISO date/datetime."""
    try:
        from .schemas import AccomplishmentCreate
        data = AccomplishmentCreate(
            title=title, occurred_at=datetime.fromisoformat(occurred_at),
            description=description, impact=impact,
            impact_evidence_url=impact_evidence_url,
            is_highlight=is_highlight, tags=tags, source_key=source_key,
        )
        result = retrospectives.create_accomplishment(_conn(), data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def record_case(
    title: str,
    occurred_at: str,
    phenomenon: str = "",
    root_cause: str | None = None,
    root_cause_confirmed: bool = False,
    solution: str | None = None,
    verification: str | None = None,
    verification_done: bool = False,
    tags: str | None = None,
    source_key: str | None = None,
) -> str:
    """Record a case/lesson learned. Tracks phenomenon, root cause, solution, and verification."""
    try:
        from .schemas import CaseCreate
        data = CaseCreate(
            title=title, occurred_at=datetime.fromisoformat(occurred_at),
            phenomenon=phenomenon, root_cause=root_cause,
            root_cause_confirmed=root_cause_confirmed,
            solution=solution, verification=verification,
            verification_done=verification_done, tags=tags, source_key=source_key,
        )
        result = retrospectives.create_case(_conn(), data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def retrospective(period: str = "year") -> str:
    """Get accomplishments, cases, and events for a period: month|quarter|year."""
    try:
        today = date.today()
        if period == "month":
            date_from = today.replace(day=1).isoformat()
        elif period == "quarter":
            q_month = ((today.month - 1) // 3) * 3 + 1
            date_from = today.replace(month=q_month, day=1).isoformat()
        else:
            date_from = today.replace(month=1, day=1).isoformat()
        date_to = today.isoformat()
        conn = _conn()
        accs, acc_total = retrospectives.list_accomplishments(conn, date_from=date_from, date_to=date_to, page_size=100)
        cases_list, case_total = retrospectives.list_cases(conn, date_from=date_from, date_to=date_to, page_size=100)
        evts, evt_total = events.search_events(conn, date_from=date_from, date_to=date_to, page_size=100)
        return json.dumps({
            "period": period, "date_from": date_from, "date_to": date_to,
            "accomplishments": accs, "cases": cases_list, "events": evts,
            "totals": {"accomplishments": acc_total, "cases": case_total, "events": evt_total},
        }, ensure_ascii=False)
    except Exception as e:
        return _err(e)


def main():
    mcp.run()


if __name__ == "__main__":
    main()