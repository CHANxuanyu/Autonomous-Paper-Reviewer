"""User account model with ownership links to documents and review tasks."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampedUUIDMixin

if TYPE_CHECKING:
    from .document import Document
    from .review_task import ReviewTask


class User(TimestampedUUIDMixin, Base):
    """Stores user identity and tier information."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")

    documents: Mapped[list["Document"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    review_tasks: Mapped[list["ReviewTask"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
