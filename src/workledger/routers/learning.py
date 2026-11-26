"""REST entry points for reviewing and reusing lessons."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..config import settings
from ..db import get_connection
from ..learning_models import (
    LessonCreate,
    LessonDraftRequest,
    LessonReview,
    LessonStatus,
    LessonUpdate,
    LessonUseCreate,
)
from ..services import learning

router = APIRouter(tags=["learning"])


def _conn():
    return get_connection(settings.db_path)


@router.get("/lessons")
def search_lessons(
    q: Annotated[str | None, Query(max_length=2000)] = None,
    status: LessonStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
):
    return learning.list_lessons(_conn(), q=q, status=status, page=page, page_size=page_size)


@router.get("/lessons/recall")
def recall_lessons(
    q: Annotated[str, Query(max_length=3000)],
    project_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    work_item_id: Annotated[int | None, Query(gt=0)] = None,
):
    return learning.recall_lessons(
        _conn(), q, project_id=project_id, limit=limit, exclude_source_work_item_id=work_item_id,
    )


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: int):
    return learning.get_lesson(_conn(), lesson_id)


@router.post("/lessons", status_code=201)
def create_lesson(data: LessonCreate):
    return learning.create_lesson(_conn(), data)


@router.patch("/lessons/{lesson_id}")
def edit_lesson(lesson_id: int, data: LessonUpdate):
    return learning.update_lesson(_conn(), lesson_id, data)


@router.post("/lessons/{lesson_id}/review")
def review_lesson(lesson_id: int, data: LessonReview):
    return learning.review_lesson(_conn(), lesson_id, data.status)


@router.post("/lessons/{lesson_id}/uses")
def record_use(lesson_id: int, data: LessonUseCreate):
    return learning.record_lesson_use(_conn(), lesson_id, **data.model_dump())


@router.post("/lessons/draft")
def draft_lesson(data: LessonDraftRequest):
    return learning.draft_lesson(_conn(), data.work_item_id, source_event_id=data.source_event_id)
