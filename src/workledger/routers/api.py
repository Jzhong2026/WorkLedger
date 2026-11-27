"""REST API endpoints shared by Web UI and external consumers."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from ..config import settings
from ..db import get_connection
from ..schemas import (
    AccomplishmentCreate,
    AccomplishmentUpdate,
    CaseCreate,
    CaseUpdate,
    EventCreate,
    EventDraftUpdate,
    EventUpdate,
    TodoCreate,
    TodoUpdate,
)
from ..services import events, retrospectives, todos
from ..services.export import Period
from .inputs import (
    ExpandedSearchRequest,
    NarrativeRequest,
    NoteCreate,
    ProjectCreate,
    ProjectUpdate,
    SearchExpansion,
    SemanticSearchRequest,
    SprintCreate,
    SprintUpdate,
)

router = APIRouter()


def _conn():
    return get_connection(settings.db_path)


def _date_window(
    date_from: date | None, date_to: date | None,
) -> dict[str, str | None]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(422, "From date must be on or before the to date.")
    return {
        "date_from": date_from.isoformat() if date_from is not None else None,
        "date_to": date_to.isoformat() if date_to is not None else None,
    }


def _page(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


# --- Events ---

@router.post("/events", status_code=201)
def create_event(data: EventCreate):
    return events.create_event(_conn(), data)


@router.get("/events")
def search_events(
    q: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    jira_key: str | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = Query(None, ge=0),
    root_cause: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = events.search_events(
        _conn(), q=q, repo=repo, pr_number=pr_number, jira_key=jira_key,
        event_type=event_type, project_id=project_id, root_cause=root_cause,
        page=page, page_size=page_size, **_date_window(date_from, date_to),
    )
    return _page(items, total, page, page_size)


@router.get("/events/{event_id}")
def get_event(event_id: int):
    result = events.get_event(_conn(), event_id)
    if not result:
        raise HTTPException(404, f"Event {event_id} not found")
    return result


@router.get("/events/{event_id}/children")
def get_event_children(event_id: int):
    return events.get_children(_conn(), event_id)


@router.patch("/events/{event_id}")
def update_event(event_id: int, data: EventUpdate):
    result = events.update_event(_conn(), event_id, data)
    if not result:
        raise HTTPException(404, f"Event {event_id} not found")
    return result


@router.get("/prs/timeline")
def pr_timeline(repo: str, pr_number: int):
    return events.get_pr_timeline(_conn(), repo, pr_number)


@router.get("/repos")
def list_repos():
    return events.list_repos(_conn())


# --- Todos ---

@router.post("/todos", status_code=201)
def create_todo(data: TodoCreate):
    return todos.create_todo(_conn(), data)


@router.get("/todos")
def list_todos(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    items, total = todos.list_todos(
        _conn(), status=status, project_id=project_id,
        page=page, page_size=page_size, **_date_window(date_from, date_to),
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "pages": pages, "today": date.today().isoformat(),
    }


@router.get("/todos/today")
def today_todos():
    today = date.today().isoformat()
    return todos.today_todos(_conn(), today)


@router.get("/todos/today-summary")
def today_summary():
    return todos.today_summary(_conn(), date.today().isoformat())


@router.get("/todos/{todo_id}")
def get_todo(todo_id: int):
    result = todos.get_todo(_conn(), todo_id)
    if not result:
        raise HTTPException(404, f"Todo {todo_id} not found")
    return result


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: int, data: TodoUpdate):
    result = todos.update_todo(_conn(), todo_id, data)
    if not result:
        raise HTTPException(404, f"Todo {todo_id} not found")
    return result


@router.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int):
    if not todos.delete_todo(_conn(), todo_id):
        raise HTTPException(404, f"Todo {todo_id} not found")


# --- Accomplishments ---

@router.post("/accomplishments", status_code=201)
def create_accomplishment(data: AccomplishmentCreate):
    return retrospectives.create_accomplishment(_conn(), data)


@router.get("/accomplishments")
def list_accomplishments(
    date_from: str | None = None,
    date_to: str | None = None,
    highlight_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = retrospectives.list_accomplishments(
        _conn(), date_from=date_from, date_to=date_to,
        highlight_only=highlight_only, page=page, page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/accomplishments/{acc_id}")
def get_accomplishment(acc_id: int):
    result = retrospectives.get_accomplishment(_conn(), acc_id)
    if not result:
        raise HTTPException(404, f"Accomplishment {acc_id} not found")
    return result


@router.patch("/accomplishments/{acc_id}")
def update_accomplishment(acc_id: int, data: AccomplishmentUpdate):
    result = retrospectives.update_accomplishment(_conn(), acc_id, data)
    if not result:
        raise HTTPException(404, f"Accomplishment {acc_id} not found")
    return result


# --- Cases ---

@router.post("/cases", status_code=201)
def create_case(data: CaseCreate):
    return retrospectives.create_case(_conn(), data)


@router.get("/cases")
def list_cases(
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = retrospectives.list_cases(
        _conn(), date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/cases/{case_id}")
def get_case(case_id: int):
    result = retrospectives.get_case(_conn(), case_id)
    if not result:
        raise HTTPException(404, f"Case {case_id} not found")
    return result


@router.patch("/cases/{case_id}")
def update_case(case_id: int, data: CaseUpdate):
    result = retrospectives.update_case(_conn(), case_id, data)
    if not result:
        raise HTTPException(404, f"Case {case_id} not found")
    return result


# --- Retrospective period helper ---

@router.get("/retrospective")
def retrospective(
    period: Period = "year",
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
):
    from ..services.export import retrospective_page

    return retrospective_page(_conn(), period, page=page, page_size=page_size)


# --- Agent settings ---

@router.get("/agent/status")
def agent_status():
    from ..agent import get_agent_status
    s = get_agent_status()
    return {
        "enabled": s.enabled,
        "model": s.model,
        "cli_available": s.cli_available,
        "key_configured": s.key_configured,
        "connection_ok": s.connection_ok,
        "error": s.error,
    }


@router.post("/agent/test-connection")
def agent_test_connection(model: str | None = None):
    from ..agent import test_connection
    return test_connection(model)


# --- Projects ---

@router.get("/projects")
def list_projects(include_archived: bool = False):
    from ..services import master_data
    return master_data.list_projects(_conn(), include_archived=include_archived)


@router.post("/projects", status_code=201)
def create_project(data: ProjectCreate):
    from ..services import master_data
    return master_data.create_project(_conn(), **data.model_dump())


@router.get("/projects/{project_id}")
def get_project(project_id: int):
    from ..services import master_data
    result = master_data.get_project(_conn(), project_id)
    if not result:
        raise HTTPException(404, f"Project {project_id} not found")
    return result


@router.patch("/projects/{project_id}")
def update_project(project_id: int, data: ProjectUpdate):
    from ..services import master_data
    result = master_data.update_project(_conn(), project_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, f"Project {project_id} not found")
    return result


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int):
    from ..services import master_data
    if not master_data.delete_project(_conn(), project_id):
        raise HTTPException(404, f"Project {project_id} not found")


# --- Sprints ---

@router.get("/sprints")
def list_sprints(project_id: int | None = None, status: str | None = None):
    from ..services import master_data
    return master_data.list_sprints(_conn(), project_id=project_id, status=status)


@router.post("/sprints", status_code=201)
def create_sprint(data: SprintCreate):
    from ..services import master_data
    return master_data.create_sprint(_conn(), **data.model_dump(mode="json"))


@router.get("/sprints/{sprint_id}")
def get_sprint(sprint_id: int):
    from ..services import master_data
    result = master_data.get_sprint(_conn(), sprint_id)
    if not result:
        raise HTTPException(404, f"Sprint {sprint_id} not found")
    return result


@router.patch("/sprints/{sprint_id}")
def update_sprint(sprint_id: int, data: SprintUpdate):
    from ..services import master_data
    result = master_data.update_sprint(
        _conn(), sprint_id, **data.model_dump(mode="json", exclude_unset=True)
    )
    if not result:
        raise HTTPException(404, f"Sprint {sprint_id} not found")
    return result


@router.delete("/sprints/{sprint_id}", status_code=204)
def delete_sprint(sprint_id: int):
    from ..services import master_data
    if not master_data.delete_sprint(_conn(), sprint_id):
        raise HTTPException(404, f"Sprint {sprint_id} not found")


# --- Inbox & drafts ---

@router.post("/inbox", status_code=201)
def capture_note(data: NoteCreate):
    from ..services import inbox
    return inbox.create_note(_conn(), data.raw_text)


@router.get("/inbox")
def list_inbox(status: str | None = None):
    from ..services import inbox
    return inbox.list_notes(_conn(), status=status)


@router.post("/inbox/{note_id}/structure")
def structure_note(note_id: int, model: str | None = None):
    from ..agent import structure_note as agent_structure
    from ..services import inbox
    note = inbox.get_note(_conn(), note_id)
    if not note:
        raise HTTPException(404, f"Note {note_id} not found")
    if note["status"] != "raw":
        raise HTTPException(409, "Only unprocessed notes can be structured.")
    result = agent_structure(note["raw_text"], model=model)
    if not result.get("ok"):
        raise HTTPException(503, result.get("error", "Agent unavailable"))
    drafts = inbox.save_drafts(_conn(), note_id, result["events"])
    return {"note_id": note_id, "drafts": drafts}


@router.post("/inbox/{note_id}/commit")
def commit_note(note_id: int, data: EventDraftUpdate):
    from ..services import inbox
    return inbox.commit_note(_conn(), note_id, data)


@router.get("/drafts")
def list_drafts(note_id: int | None = None, status: str | None = "pending"):
    from ..services import inbox
    return inbox.list_drafts(_conn(), note_id=note_id, status=status)


@router.post("/drafts/{draft_id}/confirm")
def confirm_draft(draft_id: int, data: EventDraftUpdate | None = None):
    from ..services import inbox
    return inbox.confirm_draft(_conn(), draft_id, data)


@router.patch("/drafts/{draft_id}")
def update_draft(draft_id: int, data: EventDraftUpdate):
    from ..services import inbox
    return inbox.update_draft(_conn(), draft_id, data)


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int):
    from ..services import inbox
    if not inbox.discard_draft(_conn(), draft_id):
        raise HTTPException(404, f"Pending draft {draft_id} not found")
    return {"discarded": draft_id}


@router.post("/inbox/{note_id}/discard")
def discard_note(note_id: int):
    from ..services import inbox
    if not inbox.discard_note(_conn(), note_id):
        raise HTTPException(404, f"Note {note_id} not found")
    return {"discarded": note_id}


# --- Full-text search ---

@router.get("/search/fts")
def search_fts(
    q: str,
    repo: str | None = None,
    event_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = events.search_fts(_conn(), q, repo=repo, event_type=event_type, page=page, page_size=page_size)
    return _page(items, total, page, page_size)


def _expanded_results(expansion: SearchExpansion, page: int, page_size: int) -> dict:
    keywords = events.split_expansion_keywords(expansion.keywords)
    if not keywords:
        raise HTTPException(422, "Enter at least one search term.")
    items, total = events.search_fts(
        _conn(), "", repo=expansion.repo or None, event_type=expansion.event_type,
        keywords=keywords, page=page, page_size=page_size,
    )
    return {
        **_page(items, total, page, page_size),
        "expansion": {**expansion.model_dump(), "keywords": ", ".join(keywords)},
    }


@router.post("/search/semantic")
def search_semantic(data: SemanticSearchRequest):
    from ..agent import expand_query

    result = expand_query(data.question, model=data.model)
    if not result.get("ok"):
        raise HTTPException(503, result.get("error") or "Agent unavailable. Try keyword search.")
    try:
        expansion = SearchExpansion.model_validate(result)
    except ValidationError as exc:
        raise HTTPException(502, "The model returned invalid search terms. Try keyword search.") from exc
    if not events.split_expansion_keywords(expansion.keywords):
        raise HTTPException(502, "The model returned no search terms. Try keyword search.")
    return _expanded_results(expansion, data.page, data.page_size)


@router.post("/search/expanded")
def search_expanded(data: ExpandedSearchRequest):
    return _expanded_results(data.expansion, data.page, data.page_size)


# --- Export ---

@router.get("/export")
def export_markdown(period: Period = "year", scope: Literal["all", "mine"] = "all"):
    from fastapi.responses import PlainTextResponse

    from ..services import export
    md = export.export_markdown(_conn(), period, scope=scope)
    return PlainTextResponse(md, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="workledger-{period}.md"'
    })


@router.post("/export/narrative")
def export_narrative(data: NarrativeRequest):
    from ..agent import synthesize_narrative
    from ..services import export

    today = date.today()
    try:
        md, coverage = export.narrative_input(_conn(), data.period, today=today, scope=data.scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = synthesize_narrative(md, data.period, model=data.model)
    if not result.get("ok"):
        raise HTTPException(503, result.get("error") or "Agent unavailable. You can still export Markdown.")
    date_from, date_to = export.period_range(data.period, today=today)
    return {
        "period": data.period, "date_from": date_from, "date_to": date_to,
        "narrative": result["narrative"], "coverage": coverage,
    }


# --- Insights ---

@router.get("/insights")
def get_insights(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = Query(None, ge=0),
):
    from ..services import insights
    return insights.get_insights(_conn(), project_id=project_id, **_date_window(date_from, date_to))


# --- Evidence snapshot ---

@router.post("/events/{event_id}/snapshot")
def snapshot_event(event_id: int):
    from ..services import evidence
    return evidence.capture_snapshot(_conn(), event_id)
