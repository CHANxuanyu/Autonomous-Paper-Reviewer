"""Vectorized document chunk model used by the RAG retrieval layer."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import VECTOR as Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedUUIDMixin

if TYPE_CHECKING:
    from .document import Document
    from .evidence import Evidence


class VectorChunk(TimestampedUUIDMixin, Base):
    """Stores chunk text, position metadata, and pgvector embedding."""

    __tablename__ = "vector_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    # OpenAI text-embedding-3-small outputs 1536-dimensional embeddings.
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="vector_chunks")
    evidences: Mapped[list["Evidence"]] = relationship(back_populates="chunk")
