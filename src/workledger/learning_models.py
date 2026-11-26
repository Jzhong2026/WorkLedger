"""Validated inputs for reusable work lessons and their outcomes."""
from __future__ import annotations

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

LessonKind = Literal["skill", "process"]
LessonStatus = Literal["candidate", "confirmed", "declined"]
LessonReviewStatus = Literal["confirmed", "declined"]
LessonUseOutcome = Literal["applied", "helped", "did_not_help"]
PositiveId = Annotated[int, Field(gt=0)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
Trigger = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
FirstStep = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1800)]
Limits = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=48)]
Tags = Annotated[list[Tag], Field(max_length=12)]
EvidenceUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class LessonText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LessonKind
    title: Title
    trigger: Trigger
    first_step: FirstStep
    limits: Limits | None = None
    tags: Tags = Field(default_factory=list)

    @field_validator("limits")
    @classmethod
    def normalize_limits(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, tags: list[str]) -> list[str]:
        values = {}
        for tag in tags:
            values.setdefault(tag.casefold(), tag)
        return list(values.values())


def _evidence_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
        raise ValueError("Evidence must be an HTTP(S) URL without credentials.")
    return value


class LessonCreate(LessonText):
    source_work_item_id: PositiveId
    source_event_id: PositiveId | None = None
    evidence_url: EvidenceUrl | None = None

    _valid_url = field_validator("evidence_url")(_evidence_url)


class LessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LessonKind | None = None
    title: Title | None = None
    trigger: Trigger | None = None
    first_step: FirstStep | None = None
    limits: Limits | None = None
    tags: Tags | None = None
    source_event_id: PositiveId | None = None
    evidence_url: EvidenceUrl | None = None

    _valid_url = field_validator("evidence_url")(_evidence_url)

    @model_validator(mode="after")
    def require_populated_fields(self) -> Self:
        for field in ("kind", "title", "trigger", "first_step", "tags"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class LessonReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: LessonReviewStatus


class LessonUseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: PositiveId
    outcome: LessonUseOutcome
    detail: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)] | None = None


class LessonDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_item_id: PositiveId
    source_event_id: PositiveId | None = None
