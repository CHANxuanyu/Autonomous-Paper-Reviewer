"""FastAPI routes for document upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from core.db import get_db
from schemas.document import DocumentCreateResponse
from services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF and create a document record",
)
async def create_document(
    file: UploadFile = File(..., description="PDF file to analyze"),
    db: Session = Depends(get_db),
) -> DocumentCreateResponse:
    """Accept a PDF upload and delegate persistence to the document service."""

    return await document_service.create_document(db=db, file=file)
