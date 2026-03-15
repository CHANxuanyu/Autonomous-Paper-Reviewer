"""Repository functions for VectorChunk and Evidence persistence."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.evidence import Evidence
from models.vector_chunk import VectorChunk


def create_vector_chunks(
    db: Session,
    *,
    document_id: UUID,
    chunks: Sequence[dict[str, Any]],
    embeddings: Sequence[list[float]],
) -> list[VectorChunk]:
    """Batch insert vector chunks for a document."""

    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must have the same length")

    vector_chunks: list[VectorChunk] = []
    for index, (chunk_payload, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
        vector_chunk = VectorChunk(
            document_id=document_id,
            chunk_text=chunk_payload["chunk_text"],
            embedding=embedding,
            page_number=chunk_payload.get("page_number"),
            section_name=chunk_payload.get("section_name"),
            chunk_index=chunk_payload.get("chunk_index", index),
            token_count=chunk_payload.get("token_count"),
            linked_image_path=chunk_payload.get("linked_image_path"),
        )
        vector_chunks.append(vector_chunk)

    db.add_all(vector_chunks)
    db.flush()
    return vector_chunks


def delete_vector_chunks_by_document_id(db: Session, *, document_id: UUID) -> None:
    """Remove all vector chunks for a document."""

    db.execute(delete(VectorChunk).where(VectorChunk.document_id == document_id))
    db.flush()


def create_evidences(
    db: Session,
    *,
    review_task_id: UUID,
    evidences: Sequence[dict[str, Any]],
) -> list[Evidence]:
    """Batch insert evidence rows for a review task."""

    evidence_rows: list[Evidence] = []
    for evidence_payload in evidences:
        confidence_score = evidence_payload["confidence_score"]
        if isinstance(confidence_score, Decimal):
            confidence_score = float(confidence_score)

        evidence = Evidence(
            review_task_id=review_task_id,
            chunk_id=evidence_payload["chunk_id"],
            claim=evidence_payload["claim"],
            confidence_score=confidence_score,
            evidence_type=evidence_payload["evidence_type"],
        )
        evidence_rows.append(evidence)

    db.add_all(evidence_rows)
    db.flush()
    return evidence_rows


def list_evidences_by_task_id(db: Session, *, review_task_id: UUID) -> list[tuple[Evidence, VectorChunk]]:
    """Return evidence rows joined with their source chunks."""

    stmt = (
        select(Evidence, VectorChunk)
        .join(VectorChunk, Evidence.chunk_id == VectorChunk.id)
        .where(Evidence.review_task_id == review_task_id)
        .order_by(Evidence.created_at.asc())
    )
    return list(db.execute(stmt).all())
