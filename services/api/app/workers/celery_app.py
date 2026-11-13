"""Celery application.

Redis delivers tasks only; PostgreSQL stays the source of truth. Concurrency
and task routing are refined in later stages (outbox publisher, send workers,
event processor).
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "email_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Task modules are named explicitly: the worker command only imports this
    # module, so without ``include`` no task would ever be registered.
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
)
