"""Concrete review service implementation for task creation and polling."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from repositories import document_repository, review_task_repository
from schemas.review import ReviewCreateRequest, ReviewCreateResponse, ReviewReadResponse
from schemas.enums import DocumentStatus, ReviewTaskStatus
from schemas.review import ReviewResultSchema
from services.document_service import _get_or_create_mvp_user
from workers.review_tasks import run_review_task


async def create_review_task(db: Session, payload: ReviewCreateRequest) -> ReviewCreateResponse:
    """Validate ownership/state, create the task row, and enqueue the worker."""

    user = _get_or_create_mvp_user(db)
    document = document_repository.get_document_by_id_and_user(
        db,
        document_id=payload.document_id,
        user_id=user.id,
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if document.status == DocumentStatus.FAILED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create a review task for a failed document.",
        )

    review_task = review_task_repository.create_review_task(
        db,
        document_id=document.id,
        user_id=user.id,
        status=ReviewTaskStatus.PENDING.value,
        focus_areas=payload.focus_areas,
    )
    db.commit()
    db.refresh(review_task)

    try:
        run_review_task.delay(str(review_task.id))
    except Exception as exc:
        review_task_repository.update_review_task(
            db,
            review_task=review_task,
            status=ReviewTaskStatus.FAILED.value,
            error_message=f"Failed to enqueue review task: {exc}",
        )
        db.commit()
        db.refresh(review_task)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to enqueue review task: {exc}",
        ) from exc

    return ReviewCreateResponse(task_id=review_task.id, status=ReviewTaskStatus(review_task.status))


async def get_review_task(db: Session, task_id: UUID) -> ReviewReadResponse:
    """Return the latest task status and optional review result."""

    user = _get_or_create_mvp_user(db)
    review_task = review_task_repository.get_review_task_by_id_and_user(
        db,
        task_id=task_id,
        user_id=user.id,
    )
    if review_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review task not found.")

    result_json = None
    if review_task.result_json is not None:
        result_json = ReviewResultSchema.model_validate(review_task.result_json)

    return ReviewReadResponse(
        task_id=review_task.id,
        status=ReviewTaskStatus(review_task.status),
        result_json=result_json,
        error_message=review_task.error_message,
        retry_count=review_task.retry_count,
        started_at=review_task.started_at,
        completed_at=review_task.completed_at,
    )
