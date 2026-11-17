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


# --- Master Data: Projects & Sprints ---

@mcp.tool()
def create_project(name: str, key: str, repo: str | None = None, description: str | None = None, color: str = "#2563eb") -> str:
    """Create a project for organizing work events and todos. key: short uppercase code (unique)."""
    try:
        from .services import master_data
        result = master_data.create_project(_conn(), name=name, key=key, repo=repo, description=description, color=color)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_projects(include_archived: bool = False) -> str:
    """List all projects. Optionally include archived ones."""
    try:
        from .services import master_data
        result = master_data.list_projects(_conn(), include_archived=include_archived)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def update_project(project_id: int, name: str | None = None, key: str | None = None, repo: str | None = None, description: str | None = None, color: str | None = None, is_archived: bool | None = None) -> str:
    """Update a project's fields. Set is_archived=true to archive."""
    try:
        from .services import master_data
        result = master_data.update_project(_conn(), project_id, name=name, key=key, repo=repo, description=description, color=color, is_archived=is_archived)
        if not result:
            return json.dumps({"error": f"Project {project_id} not found"})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def delete_project(project_id: int) -> str:
    """Delete a project. Events/todos linked to it will have project_id set to null."""
    try:
        from .services import master_data
        ok = master_data.delete_project(_conn(), project_id)
        return json.dumps({"deleted": ok, "project_id": project_id})
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_sprint(project_id: int, name: str, start_date: str, end_date: str, goal: str | None = None, status: str = "planned") -> str:
    """Create a sprint under a project. dates: YYYY-MM-DD. status: planned|active|completed. Only one active sprint per project."""
    try:
        from .services import master_data
        result = master_data.create_sprint(_conn(), project_id=project_id, name=name, start_date=start_date, end_date=end_date, goal=goal, status=status)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_sprints(project_id: int | None = None, status: str | None = None) -> str:
    """List sprints, optionally filtered by project and/or status (planned|active|completed)."""
    try:
        from .services import master_data
        result = master_data.list_sprints(_conn(), project_id=project_id, status=status)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def update_sprint(sprint_id: int, name: str | None = None, goal: str | None = None, start_date: str | None = None, end_date: str | None = None, status: str | None = None) -> str:
    """Update a sprint. Setting status=active auto-deactivates other active sprints in the same project."""
    try:
        from .services import master_data
        result = master_data.update_sprint(_conn(), sprint_id, name=name, goal=goal, start_date=start_date, end_date=end_date, status=status)
        if not result:
            return json.dumps({"error": f"Sprint {sprint_id} not found"})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def delete_sprint(sprint_id: int) -> str:
    """Delete a sprint. Events/todos linked to it will have sprint_id set to null."""
    try:
        from .services import master_data
        ok = master_data.delete_sprint(_conn(), sprint_id)
        return json.dumps({"deleted": ok, "sprint_id": sprint_id})
    except Exception as e:
        return _err(e)


# --- Quick Inbox ---

@mcp.tool()
def capture_note(raw_text: str) -> str:
    """Capture a quick natural-language work note into the inbox. Works offline; structure it later."""
    try:
        from .services import inbox
        return json.dumps(inbox.create_note(_conn(), raw_text), ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_inbox(status: str | None = None) -> str:
    """List inbox notes. status: raw|structured|committed|discarded (omit for all)."""
    try:
        from .services import inbox
        return json.dumps(inbox.list_notes(_conn(), status=status), ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def structure_note(note_id: int) -> str:
    """Use the built-in agent (LLM) to parse an inbox note into draft events. Requires agent key. Drafts need human confirm."""
    try:
        from .services import inbox
        from .agent import structure_note as agent_structure
        note = inbox.get_note(_conn(), note_id)
        if not note:
            return json.dumps({"error": f"Note {note_id} not found"})
        result = agent_structure(note["raw_text"])
        if not result.get("ok"):
            return json.dumps(result)
        drafts = inbox.save_drafts(_conn(), note_id, result["events"])
        return json.dumps({"note_id": note_id, "drafts": drafts}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def list_drafts(note_id: int | None = None) -> str:
    """List pending event drafts awaiting confirmation."""
    try:
        from .services import inbox
        return json.dumps(inbox.list_drafts(_conn(), note_id=note_id), ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def confirm_draft(draft_id: int) -> str:
    """Confirm a draft event, committing it to work_events. Returns the created event."""
    try:
        from .services import inbox
        return json.dumps(inbox.confirm_draft(_conn(), draft_id), ensure_ascii=False)
    except Exception as e:
        return _err(e)


# --- Full-text & semantic search ---

@mcp.tool()
def search_fulltext(q: str, repo: str | None = None, event_type: str | None = None, page: int = 1) -> str:
    """Full-text search (FTS5, Chinese + English) over work events. Faster and more accurate than keyword LIKE."""
    try:
        items, total = events.search_fts(_conn(), q, repo=repo, event_type=event_type, page=page)
        return json.dumps({"items": items, "total": total, "page": page}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def search_semantic(question: str) -> str:
    """Answer a vague question about past work. Agent expands it into search keywords, then retrieves matching events. Requires agent key."""
    try:
        from .agent import expand_query
        expansion = expand_query(question)
        if not expansion.get("ok"):
            return json.dumps(expansion)
        keywords = [k.strip() for k in expansion["keywords"].split(",") if k.strip()][:5]
        raw_match = " OR ".join('"' + k.replace('"', '""') + '"' for k in keywords) if keywords else None
        items, total = events.search_fts(_conn(), expansion["keywords"], repo=expansion.get("repo"), event_type=expansion.get("event_type"), raw_match=raw_match)
        return json.dumps({"expansion": expansion, "items": items, "total": total}, ensure_ascii=False)
    except Exception as e:
        return _err(e)


# --- Export ---

@mcp.tool()
def export_retrospective(period: str = "year") -> str:
    """Export a structured Markdown retrospective (accomplishments, cases, events + evidence). period: month|quarter|year|all."""
    try:
        from .services import export
        return export.export_markdown(_conn(), period)
    except Exception as e:
        return _err(e)


@mcp.tool()
def export_narrative(period: str = "year") -> str:
    """Agent-synthesized prose retrospective grounded in recorded work. Requires agent key. States coverage gaps, no fabrication."""
    try:
        from .services import export
        from .agent import synthesize_narrative
        md = export.export_markdown(_conn(), period)
        result = synthesize_narrative(md, period)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return _err(e)


def main():
    mcp.run()


if __name__ == "__main__":
    main()