"""Web UI routes serving Jinja2 templates."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from ..config import settings
from ..db import get_connection
from ..services import events, retrospectives, todos

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _conn():
    return get_connection(settings.db_path)


@router.get("/")
def today_page(request: Request):
    today = date.today().isoformat()
    conn = _conn()
    items = todos.today_todos(conn, today)
    all_todos, total = todos.list_todos(conn)
    pending = sum(1 for t in all_todos if t["status"] == "pending")
    waiting = sum(1 for t in all_todos if t["status"] == "waiting")
    done = sum(1 for t in all_todos if t["status"] == "done")
    return templates.TemplateResponse(request, "today.html", {
        "todos": items, "today": today,
        "stats": {"pending": pending, "waiting": waiting, "done": done},
    })


@router.get("/search")
def search_page(
    request: Request,
    q: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
):
    items, total = events.search_events(
        _conn(), q=q, repo=repo, pr_number=pr_number, event_type=event_type,
        date_from=date_from, date_to=date_to, page=page, page_size=20,
    )
    repos = events.list_repos(_conn())
    pages = (total + 19) // 20 if total else 0
    return templates.TemplateResponse(request, "search.html", {
        "items": items, "total": total, "page": page, "pages": pages,
        "q": q or "", "repo": repo or "", "pr_number": pr_number,
        "event_type": event_type or "", "date_from": date_from or "",
        "date_to": date_to or "", "repos": repos,
    })


@router.get("/pr")
def pr_page(request: Request, repo: str, pr_number: int):
    timeline = events.get_pr_timeline(_conn(), repo, pr_number)
    return templates.TemplateResponse(request, "pr_timeline.html", {
        "repo": repo, "pr_number": pr_number, "timeline": timeline,
    })


@router.get("/event/{event_id}")
def event_detail(request: Request, event_id: int):
    ev = events.get_event(_conn(), event_id)
    return templates.TemplateResponse(request, "event_detail.html", {"event": ev})


@router.get("/retrospective")
def retrospective_page(request: Request, period: str = "year"):
    today = date.today()
    if period == "month":
        date_from = today.replace(day=1).isoformat()
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_month, day=1).isoformat()
    else:
        date_from = today.replace(month=1, day=1).isoformat()
    date_to = today.isoformat()

    accs, _ = retrospectives.list_accomplishments(_conn(), date_from=date_from, date_to=date_to, page_size=100)
    cases_list, _ = retrospectives.list_cases(_conn(), date_from=date_from, date_to=date_to, page_size=100)
    return templates.TemplateResponse(request, "retrospective.html", {
        "period": period, "date_from": date_from, "date_to": date_to,
        "accomplishments": accs, "cases": cases_list,
    })


@router.get("/todos")
def todos_page(request: Request, status: str | None = None):
    items, total = todos.list_todos(_conn(), status=status)
    return templates.TemplateResponse(request, "todos.html", {
        "todos": items, "total": total, "status_filter": status or "",
    })


@router.get("/settings")
def settings_page(request: Request):
    from ..services import master_data
    conn = _conn()
    projects = master_data.list_projects(conn, include_archived=True)
    sprints = master_data.list_sprints(conn)
    project_map = {p["id"]: p["key"] for p in projects}
    return templates.TemplateResponse(request, "settings.html", {
        "projects": projects, "sprints": sprints, "project_map": project_map,
    })