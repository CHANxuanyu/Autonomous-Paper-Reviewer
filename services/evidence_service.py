"""Concrete evidence service implementation for traceability responses."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from repositories import evidence_repository, review_task_repository
from schemas.evidence import EvidenceListResponse, EvidenceRead
from services.document_service import _get_or_create_mvp_user


async def list_review_evidences(db: Session, task_id: UUID) -> EvidenceListResponse:
    """Aggregate evidence rows and chunk context for the API response."""

    user = _get_or_create_mvp_user(db)
    review_task = review_task_repository.get_review_task_by_id_and_user(
        db,
        task_id=task_id,
        user_id=user.id,
    )
    if review_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review task not found.")

    rows = evidence_repository.list_evidences_by_task_id(db, review_task_id=review_task.id)
    evidences = [
        EvidenceRead(
            claim=evidence.claim,
            confidence_score=float(evidence.confidence_score),
            chunk_id=evidence.chunk_id,
            evidence_type=evidence.evidence_type,
            page_number=chunk.page_number,
            chunk_text=chunk.chunk_text,
        )
        for evidence, chunk in rows
    ]

    return EvidenceListResponse(task_id=review_task.id, evidences=evidences)
