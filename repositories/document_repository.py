"""Repository functions for the Document ORM model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.document import Document


def create_document(
    db: Session,
    *,
    user_id: UUID,
    title: str | None,
    file_url: str,
    status: str,
    metadata_json: dict[str, Any] | None = None,
) -> Document:
    """Create a document row and flush it so the caller can commit."""

    document = Document(
        user_id=user_id,
        title=title,
        file_url=file_url,
        status=status,
        metadata_json=metadata_json,
    )
    db.add(document)
    db.flush()
    return document


def get_document_by_id(db: Session, document_id: UUID) -> Document | None:
    """Fetch a document by primary key."""

    return db.scalar(select(Document).where(Document.id == document_id))


def get_document_by_id_and_user(db: Session, *, document_id: UUID, user_id: UUID) -> Document | None:
    """Fetch a document owned by a specific user."""

    stmt = select(Document).where(Document.id == document_id, Document.user_id == user_id)
    return db.scalar(stmt)


def update_document_status(db: Session, *, document: Document, status: str) -> Document:
    """Update the document processing status."""

    document.status = status
    db.add(document)
    db.flush()
    return document


def update_document_metadata(
    db: Session,
    *,
    document: Document,
    title: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> Document:
    """Update parsed document metadata fields."""

    if title is not None:
        document.title = title
    if metadata_json is not None:
        document.metadata_json = metadata_json
    db.add(document)
    db.flush()
    return document


def delete_document(db: Session, *, document: Document) -> None:
    """Delete a document row."""

    db.delete(document)
    db.flush()
