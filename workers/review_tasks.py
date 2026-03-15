"""Celery worker skeleton for the asynchronous review pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.celery_app import celery_app
from core.db import SessionLocal
from models.document import Document
from models.evidence import Evidence
from models.review_task import ReviewTask
from models.user import User
from models.vector_chunk import VectorChunk
from agents import orchestrator, reviewer
from rag import chunker, embedder, parser, retriever
from repositories import evidence_repository
from schemas.enums import DocumentStatus, ReviewTaskStatus
from schemas.review import ReviewResultSchema

STAGE_RETRY_LIMITS: dict[ReviewTaskStatus, int] = {
    ReviewTaskStatus.PARSING_DOC: 2,
    ReviewTaskStatus.VECTORIZING: 3,
    ReviewTaskStatus.AGENT_PLANNING: 2,
    ReviewTaskStatus.EVIDENCE_RETRIEVAL: 2,
    ReviewTaskStatus.REPORT_GENERATING: 2,
}

def get_worker_session() -> Session:
    """Create a synchronous SQLAlchemy session for a worker task."""

    return SessionLocal()


def persist_vector_chunks(
    db: Session,
    *,
    document_id: UUID,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """Persist vector chunks for a document."""

    evidence_repository.create_vector_chunks(
        db,
        document_id=document_id,
        chunks=chunks,
        embeddings=embeddings,
    )


def cleanup_vector_chunks(db: Session, *, document_id: UUID) -> None:
    """Remove old chunks before a VECTORIZING retry to keep the task idempotent."""

    evidence_repository.delete_vector_chunks_by_document_id(db, document_id=document_id)


def persist_review_output(
    db: Session,
    *,
    review_task: ReviewTask,
    report_payload: dict[str, Any],
    evidences: list[dict[str, Any]],
) -> None:
    """Persist result_json and evidence rows in one transaction boundary."""

    review_task.result_json = report_payload
    db.add(review_task)
    db.flush()
    evidence_repository.create_evidences(
        db,
        review_task_id=review_task.id,
        evidences=evidences,
    )


def _set_review_status(db: Session, review_task: ReviewTask, status: ReviewTaskStatus) -> None:
    """Persist a state-machine transition immediately."""

    review_task.status = status.value
    review_task.error_message = None
    if status == ReviewTaskStatus.PARSING_DOC and review_task.started_at is None:
        review_task.started_at = datetime.now(timezone.utc)
    db.add(review_task)
    db.commit()
    db.refresh(review_task)


def _mark_review_failed(
    db: Session,
    review_task: ReviewTask,
    *,
    error_message: str,
) -> None:
    """Write terminal failure state and keep the latest error summary."""

    review_task.status = ReviewTaskStatus.FAILED.value
    review_task.error_message = error_message
    db.add(review_task)
    db.commit()
    db.refresh(review_task)


def _mark_document_failed(db: Session, document: Document) -> None:
    """Keep document status consistent when parsing ultimately fails."""

    document.status = DocumentStatus.FAILED.value
    db.add(document)
    db.commit()
    db.refresh(document)


def _retry_countdown(status: ReviewTaskStatus, retry_count: int) -> int:
    """Use a simple exponential backoff for stage retries."""

    if status == ReviewTaskStatus.VECTORIZING:
        return 2 ** retry_count
    return retry_count


@celery_app.task(bind=True, max_retries=3)
def run_review_task(self: Task, task_id: str) -> None:
    """Drive the asynchronous review workflow through the defined state machine."""

    db = get_worker_session()
    try:
        review_task = db.scalar(select(ReviewTask).where(ReviewTask.id == UUID(task_id)))
        if review_task is None:
            raise ValueError(f"review_task not found: {task_id}")

        document = db.scalar(select(Document).where(Document.id == review_task.document_id))
        if document is None:
            raise ValueError(f"document not found for task: {task_id}")
        document_id = document.id

        if review_task.status == ReviewTaskStatus.COMPLETED.value:
            return

        current_status = ReviewTaskStatus(review_task.status)

        try:
            _set_review_status(db, review_task, ReviewTaskStatus.PARSING_DOC)
            parsed_document = parser.parse_pdf(document.file_url)

            # After parsing succeeds, sync document metadata/status and commit immediately.
            document.title = parsed_document.get("title") or document.title
            document.metadata_json = parsed_document.get("metadata_json") or document.metadata_json
            document.status = DocumentStatus.PARSED.value
            db.add(document)
            db.commit()
            db.refresh(document)

            _set_review_status(db, review_task, ReviewTaskStatus.VECTORIZING)
            chunks = chunker.split_document(parsed_document)
            embeddings = embedder.embed_chunks(chunks)
            persist_vector_chunks(
                db,
                document_id=document.id,
                chunks=chunks,
                embeddings=embeddings,
            )

            # Vectorization success means the document is indexed and ready for retrieval.
            document.status = DocumentStatus.INDEXED.value
            db.add(document)
            db.commit()
            db.refresh(document)

            _set_review_status(db, review_task, ReviewTaskStatus.AGENT_PLANNING)
            review_plan = orchestrator.plan_review(review_task.focus_areas or [], parsed_document)

            _set_review_status(db, review_task, ReviewTaskStatus.EVIDENCE_RETRIEVAL)
            try:
                evidences = retriever.retrieve_evidences(document.id, review_plan, broaden=False)
            except Exception:
                # Section 9 allows one broader retrieval fallback before treating this as a hard failure.
                evidences = retriever.retrieve_evidences(document.id, review_plan, broaden=True)

            _set_review_status(db, review_task, ReviewTaskStatus.REPORT_GENERATING)
            report_payload = reviewer.generate_report(parsed_document, review_plan, evidences)
            validated_report = ReviewResultSchema.model_validate(report_payload).model_dump()

            # Persist result_json and evidences together so the API never exposes partial output.
            persist_review_output(
                db,
                review_task=review_task,
                report_payload=validated_report,
                evidences=evidences,
            )

            review_task.status = ReviewTaskStatus.COMPLETED.value
            review_task.completed_at = datetime.now(timezone.utc)
            review_task.error_message = None
            db.add(review_task)
            db.commit()
            db.refresh(review_task)

        except Exception as exc:
            current_status = ReviewTaskStatus(review_task.status)
            db.rollback()
            review_task = db.scalar(select(ReviewTask).where(ReviewTask.id == UUID(task_id)))
            document = db.scalar(select(Document).where(Document.id == document_id))
            if review_task is None or document is None:
                raise

            review_task.retry_count += 1
            review_task.error_message = str(exc)
            db.add(review_task)
            db.commit()
            db.refresh(review_task)

            if current_status == ReviewTaskStatus.VECTORIZING:
                # Section 9 requires cleanup before retry if partial chunks may already exist.
                cleanup_vector_chunks(db, document_id=document.id)
                db.commit()

            retry_limit = STAGE_RETRY_LIMITS.get(current_status, 0)
            if current_status == ReviewTaskStatus.PARSING_DOC and review_task.retry_count >= retry_limit:
                _mark_document_failed(db, document)

            if review_task.retry_count >= retry_limit:
                _mark_review_failed(db, review_task, error_message=str(exc))
                return

            raise self.retry(exc=exc, countdown=_retry_countdown(current_status, review_task.retry_count))
    finally:
        db.close()
