"""Internal schemas for richer retrieval outputs passed into reasoning stages."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RetrievedEvidenceSchema(BaseModel):
    """Rich retrieval payload used by downstream reasoning and evaluation code."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID | str
    document_id: UUID | None = None
    claim: str
    query_text: str
    aspect: str | None = None
    priority: int | None = None
    evidence_type: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    vector_distance: float = Field(ge=0.0)
    keyword_overlap: float = Field(ge=0.0, le=1.0)
    retrieval_rank: int = Field(ge=1)
    retrieval_source: str
    chunk_text: str
    page_number: int | None = None
    section_name: str | None = None
    chunk_index: int | None = None
    linked_image_path: str | None = None
