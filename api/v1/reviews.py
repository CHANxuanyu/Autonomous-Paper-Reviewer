"""FastAPI routes for review task creation, polling, and evidence lookup."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.db import get_db
from schemas.evidence import EvidenceListResponse
from schemas.review import ReviewCreateRequest, ReviewCreateResponse, ReviewReadResponse
from services import evidence_service, review_service

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewCreateResponse, summary="Create a review task")
async def create_review(
    payload: ReviewCreateRequest,
    db: Session = Depends(get_db),
) -> ReviewCreateResponse:
    """Validate the request, create the task, and enqueue the worker job."""

    return await review_service.create_review_task(db=db, payload=payload)


@router.get("/{task_id}", response_model=ReviewReadResponse, summary="Poll a review task")
async def get_review(
    task_id: UUID,
    db: Session = Depends(get_db),
) -> ReviewReadResponse:
    """Return the current workflow status and optional structured result."""

    return await review_service.get_review_task(db=db, task_id=task_id)


@router.get(
    "/{task_id}/evidences",
    response_model=EvidenceListResponse,
    summary="List evidences for a review task",
)
async def list_review_evidences(
    task_id: UUID,
    db: Session = Depends(get_db),
) -> EvidenceListResponse:
    """Return evidence records joined with chunk context for traceability."""

    return await evidence_service.list_review_evidences(db=db, task_id=task_id)
