"""Validated write inputs for web management endpoints."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..schemas import EventType
from ..services.export import Period

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
SprintStatus = Literal["planned", "active", "completed"]


class WriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(WriteInput):
    name: NonBlankText
    key: NonBlankText
    repo: str | None = None
    description: str | None = None
    color: Color = "#2563eb"


class ProjectUpdate(WriteInput):
    name: NonBlankText | None = None
    key: NonBlankText | None = None
    repo: str | None = None
    description: str | None = None
    color: Color | None = None
    is_archived: bool | None = None


class SprintCreate(WriteInput):
    project_id: int = Field(gt=0)
    name: NonBlankText
    start_date: date
    end_date: date
    goal: str | None = None
    status: SprintStatus = "planned"

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        return self


class SprintUpdate(WriteInput):
    name: NonBlankText | None = None
    start_date: date | None = None
    end_date: date | None = None
    goal: str | None = None
    status: SprintStatus | None = None


class NoteCreate(WriteInput):
    raw_text: NonBlankText


class SearchExpansion(BaseModel):
    keywords: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)]
    repo: str | None = None
    event_type: EventType | None = None


class SearchPageRequest(WriteInput):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class SemanticSearchRequest(SearchPageRequest):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    model: str | None = None


class ExpandedSearchRequest(SearchPageRequest):
    expansion: SearchExpansion


class NarrativeRequest(WriteInput):
    period: Period = "year"
    model: str | None = None
    scope: Literal["all", "mine"] = "all"
