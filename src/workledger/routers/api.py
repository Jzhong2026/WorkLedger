"""REST API endpoints shared by Web UI and external consumers."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..db import get_connection
from ..schemas import (
    AccomplishmentCreate,
    AccomplishmentUpdate,
    CaseCreate,
    CaseUpdate,
    EventCreate,
    EventUpdate,
    TodoCreate,
    TodoUpdate,
)
from ..services import events, retrospectives, todos

router = APIRouter()


def _conn():
    return get_connection(settings.db_path)


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
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = events.search_events(
        _conn(), q=q, repo=repo, pr_number=pr_number, jira_key=jira_key,
        event_type=event_type, date_from=date_from, date_to=date_to,
        page=page, page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/events/{event_id}")
def get_event(event_id: int):
    result = events.get_event(_conn(), event_id)
    if not result:
        raise HTTPException(404, f"Event {event_id} not found")
    return result


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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    items, total = todos.list_todos(_conn(), status=status, page=page, page_size=page_size)
    pages = (total + page_size - 1) // page_size if total else 0
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/todos/today")
def today_todos():
    today = date.today().isoformat()
    return todos.today_todos(_conn(), today)


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
def retrospective(period: str = "year"):
    today = date.today()
    if period == "month":
        date_from = today.replace(day=1).isoformat()
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_month, day=1).isoformat()
    else:
        date_from = today.replace(month=1, day=1).isoformat()
    date_to = today.isoformat()

    accs, acc_total = retrospectives.list_accomplishments(
        _conn(), date_from=date_from, date_to=date_to, page=1, page_size=100,
    )
    cases_list, case_total = retrospectives.list_cases(
        _conn(), date_from=date_from, date_to=date_to, page=1, page_size=100,
    )
    evts, evt_total = events.search_events(
        _conn(), date_from=date_from, date_to=date_to, page=1, page_size=100,
    )
    return {
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "accomplishments": accs,
        "cases": cases_list,
        "events": evts,
        "totals": {"accomplishments": acc_total, "cases": case_total, "events": evt_total},
    }


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