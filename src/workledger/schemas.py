"""Pydantic schemas for API input/output validation."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "pr_created", "review_finding", "comment_analysis",
    "fix", "verification", "reply_drafted", "reply_published", "manual",
]
TodoStatus = Literal["pending", "waiting", "done"]
ReplyStatus = Literal["draft", "published"]


class EventCreate(BaseModel):
    event_type: EventType
    occurred_at: datetime
    repo: str | None = None
    pr_number: int | None = None
    comment_id: str | None = None
    jira_key: str | None = None
    source_key: str | None = None
    source_agent: str | None = None
    summary: str = ""
    detail: str | None = None
    evidence_url: str | None = None
    root_cause: str | None = None
    root_cause_confirmed: bool = False
    verification_result: str | None = None
    verification_done: bool = False
    reply_status: ReplyStatus | None = None
    extra_json: str | None = None


class EventUpdate(BaseModel):
    summary: str | None = None
    detail: str | None = None
    evidence_url: str | None = None
    root_cause: str | None = None
    root_cause_confirmed: bool | None = None
    verification_result: str | None = None
    verification_done: bool | None = None
    reply_status: ReplyStatus | None = None
    jira_key: str | None = None
    extra_json: str | None = None


class EventOut(BaseModel):
    id: int
    event_type: str
    occurred_at: str
    recorded_at: str
    repo: str | None
    pr_number: int | None
    comment_id: str | None
    jira_key: str | None
    source_key: str
    source_agent: str | None
    summary: str
    detail: str | None
    evidence_url: str | None
    root_cause: str | None
    root_cause_confirmed: bool
    verification_result: str | None
    verification_done: bool
    reply_status: str | None
    extra_json: str | None
    user_edited: bool
    created_at: str
    updated_at: str


class TodoCreate(BaseModel):
    title: str
    description: str | None = None
    status: TodoStatus = "pending"
    event_id: int | None = None
    wait_target: str | None = None
    due_date: str | None = None
    next_followup: str | None = None
    source_key: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TodoStatus | None = None
    wait_target: str | None = None
    due_date: str | None = None
    next_followup: str | None = None
    event_id: int | None = None


class TodoOut(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    event_id: int | None
    wait_target: str | None
    due_date: str | None
    next_followup: str | None
    completed_at: str | None
    source_key: str | None
    created_at: str
    updated_at: str


class AccomplishmentCreate(BaseModel):
    title: str
    description: str | None = None
    occurred_at: datetime
    impact: str | None = None
    impact_evidence_url: str | None = None
    is_highlight: bool = False
    tags: str | None = None
    source_key: str | None = None


class AccomplishmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    impact: str | None = None
    impact_evidence_url: str | None = None
    is_highlight: bool | None = None
    tags: str | None = None


class AccomplishmentOut(BaseModel):
    id: int
    title: str
    description: str | None
    occurred_at: str
    impact: str | None
    impact_evidence_url: str | None
    is_highlight: bool
    tags: str | None
    source_key: str | None
    user_edited: bool
    created_at: str
    updated_at: str


class CaseCreate(BaseModel):
    title: str
    phenomenon: str = ""
    root_cause: str | None = None
    root_cause_confirmed: bool = False
    solution: str | None = None
    verification: str | None = None
    verification_done: bool = False
    occurred_at: datetime
    tags: str | None = None
    source_key: str | None = None


class CaseUpdate(BaseModel):
    title: str | None = None
    phenomenon: str | None = None
    root_cause: str | None = None
    root_cause_confirmed: bool | None = None
    solution: str | None = None
    verification: str | None = None
    verification_done: bool | None = None
    tags: str | None = None


class CaseOut(BaseModel):
    id: int
    title: str
    phenomenon: str
    root_cause: str | None
    root_cause_confirmed: bool
    solution: str | None
    verification: str | None
    verification_done: bool
    occurred_at: str
    tags: str | None
    source_key: str | None
    user_edited: bool
    created_at: str
    updated_at: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int


class SearchQuery(BaseModel):
    q: str | None = None
    repo: str | None = None
    pr_number: int | None = None
    jira_key: str | None = None
    event_type: EventType | None = None
    date_from: str | None = None
    date_to: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)