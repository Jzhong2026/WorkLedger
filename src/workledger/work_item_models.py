"""Shared input contracts for Web and MCP work-item workflows."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, field_validator

WorkItemStage = Literal["active", "waiting", "verification", "done"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]


class WorkItemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: Trimmed | None = None
    last_verified_result: Trimmed | None = None
    blocker: Trimmed | None = None
    next_step: Trimmed | None = None
    followup_date: date | None = None

    @field_validator("owner", "last_verified_result", "blocker", "next_step", mode="after")
    @classmethod
    def blank_details_are_null(cls, value: str | None) -> str | None:
        return value or None


class WorkItemCreate(WorkItemFields):
    title: NonBlank
    goal: Trimmed | None = None
    project_id: PositiveInt | None = None
    jira_key: NonBlank | None = None
    source_event_id: PositiveInt | None = None
    stage: WorkItemStage = "active"
    needs_decision: bool = False
    source_key: NonBlank | None = None
    actor: NonBlank = "user"

    @field_validator("jira_key")
    @classmethod
    def normalize_jira_key(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class HandoffTodo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonBlank
    description: Trimmed | None = None
    due_date: date | None = None
    next_followup: date | None = None


class HandoffCreate(WorkItemFields):
    expected_version: PositiveInt
    summary: NonBlank
    stage: WorkItemStage | None = None
    needs_decision: bool | None = None
    actor: NonBlank = "user"
    source_key: NonBlank | None = None
    event_ids: list[PositiveInt] = Field(default_factory=list)
    todo_ids: list[PositiveInt] = Field(default_factory=list)
    todo: HandoffTodo | None = None

    @field_validator("stage", "needs_decision")
    @classmethod
    def state_changes_cannot_be_null(cls, value: WorkItemStage | bool | None) -> WorkItemStage | bool:
        if value is None:
            raise ValueError("Omit this field to keep its current value.")
        return value

    @field_validator("event_ids", "todo_ids")
    @classmethod
    def normalize_link_ids(cls, values: list[int]) -> list[int]:
        return sorted(set(values))
