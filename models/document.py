"""Uploaded paper document model and its child review/vector records."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedUUIDMixin

if TYPE_CHECKING:
    from .review_task import ReviewTask
    from .user import User
    from .vector_chunk import VectorChunk


class Document(TimestampedUUIDMixin, Base):
    """Stores the uploaded PDF record and extracted metadata."""

    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UPLOADED", index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship(back_populates="documents")
    vector_chunks: Mapped[list["VectorChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
