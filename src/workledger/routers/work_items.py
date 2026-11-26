"""REST endpoints for active work items and the work history they reference."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..db import get_connection
from ..services import work_items
from ..work_item_models import HandoffCreate, WorkItemCreate, WorkItemStage

router = APIRouter(prefix="/work-items", tags=["Work items"])


def _page(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("")
def list_work_items(
    project_id: int | None = Query(None, gt=0),
    jira_key: str | None = None,
    stage: WorkItemStage | None = None,
    open_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    items, total = work_items.list_work_items(
        get_connection(settings.db_path), project_id=project_id, jira_key=jira_key, stage=stage,
        open_only=open_only, page=page, page_size=page_size,
    )
    return {**_page(items, total, page, page_size), "today": date.today().isoformat()}


@router.post("", status_code=201)
def create_work_item(data: WorkItemCreate) -> dict:
    return work_items.create_work_item(get_connection(settings.db_path), data)


@router.get("/discover")
def discover_events(
    project_id: int | None = Query(None, gt=0),
    jira_key: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    items, total = work_items.discover_events(
        get_connection(settings.db_path), project_id=project_id, jira_key=jira_key, page=page, page_size=page_size,
    )
    return _page(items, total, page, page_size)


@router.get("/{item_id}")
@router.get("/{item_id}/context", include_in_schema=False)
def get_context(item_id: int) -> dict:
    context = work_items.get_work_item_context(get_connection(settings.db_path), item_id)
    if context is None:
        raise HTTPException(404, f"Work item {item_id} not found.")
    return context


@router.post("/{item_id}/handoffs", status_code=201)
def record_handoff(item_id: int, data: HandoffCreate) -> dict:
    return work_items.record_handoff(get_connection(settings.db_path), item_id, data)
