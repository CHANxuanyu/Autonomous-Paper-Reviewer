"""Celery application configuration for asynchronous review execution."""

from __future__ import annotations

from celery import Celery

REDIS_BROKER_URL = "redis://localhost:6379/0"
REDIS_RESULT_BACKEND = "redis://localhost:6379/0"

celery_app = Celery(
    "academic_paper_analyzer",
    broker=REDIS_BROKER_URL,
    backend=REDIS_RESULT_BACKEND,
    include=["workers.review_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
