"""Evidence record mapping a review claim to a supporting chunk."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedUUIDMixin

if TYPE_CHECKING:
    from .review_task import ReviewTask
    from .vector_chunk import VectorChunk


class Evidence(TimestampedUUIDMixin, Base):
    """Stores a claim-to-chunk evidence mapping generated during review."""

    __tablename__ = "evidences"

    review_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vector_chunks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    review_task: Mapped["ReviewTask"] = relationship(back_populates="evidences")
    chunk: Mapped["VectorChunk"] = relationship(back_populates="evidences")
