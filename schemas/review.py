"""Pydantic schemas for review task creation and polling endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import ReviewTaskStatus


class ReviewResultSchema(BaseModel):
    """Structured review report persisted in review_tasks.result_json."""

    model_config = ConfigDict(from_attributes=True)

    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    questions_for_authors: list[str] = Field(default_factory=list)


class ReviewCreateRequest(BaseModel):
    """Request payload for creating an asynchronous review task."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    focus_areas: list[str] = Field(default_factory=list)


class ReviewCreateResponse(BaseModel):
    """Immediate acknowledgement after task creation."""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    status: ReviewTaskStatus


class ReviewReadResponse(BaseModel):
    """Polling response for a review task."""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    status: ReviewTaskStatus
    result_json: ReviewResultSchema | None = None
    error_message: str | None = None
    retry_count: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
