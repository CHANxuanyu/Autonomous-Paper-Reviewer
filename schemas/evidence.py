"""Pydantic schemas for evidence traceability endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .enums import EvidenceType


class EvidenceRead(BaseModel):
    """A single evidence item joined with chunk context."""

    model_config = ConfigDict(from_attributes=True)

    claim: str
    confidence_score: float
    chunk_id: UUID
    evidence_type: EvidenceType
    page_number: int | None = None
    chunk_text: str


class EvidenceListResponse(BaseModel):
    """Evidence list payload for a given review task."""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    evidences: list[EvidenceRead]
