"""Repository functions for the ReviewTask ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.review_task import ReviewTask


def create_review_task(
    db: Session,
    *,
    document_id: UUID,
    user_id: UUID,
    status: str,
    focus_areas: list[str] | None,
) -> ReviewTask:
    """Create a review task row and flush it so the caller can commit."""

    review_task = ReviewTask(
        document_id=document_id,
        user_id=user_id,
        status=status,
        focus_areas=focus_areas,
    )
    db.add(review_task)
    db.flush()
    return review_task


def get_review_task_by_id(db: Session, task_id: UUID) -> ReviewTask | None:
    """Fetch a review task by primary key."""

    return db.scalar(select(ReviewTask).where(ReviewTask.id == task_id))


def get_review_task_by_id_and_user(db: Session, *, task_id: UUID, user_id: UUID) -> ReviewTask | None:
    """Fetch a review task owned by a specific user."""

    stmt = select(ReviewTask).where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
    return db.scalar(stmt)


def update_review_task(
    db: Session,
    *,
    review_task: ReviewTask,
    status: str | None = None,
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    retry_count: int | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ReviewTask:
    """Update mutable review task fields."""

    if status is not None:
        review_task.status = status
    if result_json is not None:
        review_task.result_json = result_json
    if error_message is not None:
        review_task.error_message = error_message
    if retry_count is not None:
        review_task.retry_count = retry_count
    if started_at is not None:
        review_task.started_at = started_at
    if completed_at is not None:
        review_task.completed_at = completed_at
    db.add(review_task)
    db.flush()
    return review_task


def delete_review_task(db: Session, *, review_task: ReviewTask) -> None:
    """Delete a review task row."""

    db.delete(review_task)
    db.flush()
