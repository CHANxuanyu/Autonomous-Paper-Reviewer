"""Pydantic schemas for document upload and read operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .enums import DocumentStatus


class DocumentCreateResponse(BaseModel):
    """Returned after a document upload record is created."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID


class DocumentReadResponse(BaseModel):
    """Document detail payload for read endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    file_url: str
    status: DocumentStatus
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
