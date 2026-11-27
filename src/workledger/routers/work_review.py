"""Evidence-led weekly reporting and optional read-only AI briefings."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..services import work_review
from .api import _conn

router = APIRouter(prefix="/work-review")


class WeeklyRequest(BaseModel):
    day: date | None = None
    project_id: int | None = Field(default=None, gt=0)
    scope: Literal["all", "mine"] = "all"


class BriefingRequest(BaseModel):
    project_id: int | None = Field(default=None, gt=0)
    question: str | None = Field(default=None, max_length=800)


@router.get("/weekly")
def weekly(day: date | None = None, project_id: int | None = Query(None, gt=0),
           scope: Literal["all", "mine"] = "all"):
    return work_review.weekly_review(_conn(), day, project_id, scope)


@router.post("/weekly/candidates")
def candidates(data: WeeklyRequest):
    return work_review.weekly_candidates(_conn(), data.day, data.project_id, data.scope)


@router.post("/briefing")
def briefing(data: BriefingRequest):
    return work_review.project_briefing(_conn(), data.project_id, data.question)
