"""Concrete document service implementation for the MVP upload flow."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.user import User
from repositories import document_repository
from schemas.document import DocumentCreateResponse
from schemas.enums import DocumentStatus, UserTier

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
MVP_LOCAL_USER_EMAIL = "mvp-local-user@example.com"


def _get_or_create_mvp_user(db: Session) -> User:
    """Create a single local MVP user until auth is wired into the API."""

    user = db.scalar(select(User).where(User.email == MVP_LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=MVP_LOCAL_USER_EMAIL, tier=UserTier.FREE.value)
        db.add(user)
        db.flush()
        db.refresh(user)
    return user


def _build_upload_path(filename: str | None) -> Path:
    """Generate a stable local upload path under ./uploads."""

    original_name = Path(filename or "document.pdf")
    suffix = original_name.suffix or ".pdf"
    return UPLOAD_DIR / f"{uuid4()}{suffix}"


async def create_document(db: Session, file: UploadFile) -> DocumentCreateResponse:
    """Store the uploaded file and create the documents row."""

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    user = _get_or_create_mvp_user(db)
    destination = _build_upload_path(file.filename)

    try:
        await file.seek(0)
        with destination.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        document = document_repository.create_document(
            db,
            user_id=user.id,
            title=Path(file.filename or destination.name).stem,
            file_url=destination.relative_to(PROJECT_ROOT).as_posix(),
            status=DocumentStatus.UPLOADED.value,
        )
        db.commit()
        db.refresh(document)
    except Exception as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded document: {exc}",
        ) from exc

    return DocumentCreateResponse(document_id=document.id)
