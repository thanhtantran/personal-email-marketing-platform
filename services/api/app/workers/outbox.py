"""Transactional outbox dispatcher.

Claims pending outbox rows with ``FOR UPDATE SKIP LOCKED`` and hands each to the
Celery broker, marking the row published in the same transaction. A crash
between publish and commit only ever re-publishes (at-least-once), which the
idempotent consumers absorb; a crash before publish loses nothing because the
row stays pending. PostgreSQL is the source of truth, Redis only transports
(ARCHITECTURE.md section 7).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.events.intake import WEBHOOK_OUTBOX_EVENT
from app.logging import get_logger
from app.repositories.outbox_repo import OutboxRepository

logger = get_logger(__name__)

# Outbox event type -> Celery task path. An unmapped event type is a bug, so it
# is marked failed rather than retried forever.
EVENT_TASKS: dict[str, str] = {
    "campaign.dispatch": "app.workers.tasks.dispatch_campaign",
    WEBHOOK_OUTBOX_EVENT: "app.workers.tasks.process_webhook",
}

MAX_BACKOFF_SECONDS = 300


def task_for(event_type: str) -> str | None:
    return EVENT_TASKS.get(event_type)


def _backoff_seconds(attempts: int) -> int:
    return min(2 ** max(attempts, 0), MAX_BACKOFF_SECONDS)


def _celery_send(task_name: str, payload: dict) -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task(task_name, kwargs=payload)


async def dispatch_pending(
    session: AsyncSession,
    settings: Settings,
    *,
    send: Callable[[str, dict], None] | None = None,
    now: datetime | None = None,
) -> int:
    """Publish claimed outbox events and return the number published."""
    sender = send or _celery_send
    moment = now or datetime.now(UTC)
    repo = OutboxRepository(session)
    events = await repo.claim_due(now=moment, limit=settings.campaign_outbox_batch_size)

    published = 0
    for event in events:
        task_name = task_for(event.event_type)
        if task_name is None:
            await repo.mark_failed(event, error=f"no task mapped for '{event.event_type}'")
            logger.error("outbox event has no task", extra={"event_type": event.event_type})
            continue
        try:
            sender(task_name, dict(event.payload))
        except Exception as exc:  # noqa: BLE001 - any publish failure is retryable
            error = type(exc).__name__
            if event.attempts + 1 >= settings.campaign_outbox_max_attempts:
                await repo.mark_failed(event, error=error)
                logger.error(
                    "outbox event failed permanently",
                    extra={"event_id": str(event.id), "error": error},
                )
            else:
                await repo.schedule_retry(
                    event,
                    error=error,
                    retry_at=moment + timedelta(seconds=_backoff_seconds(event.attempts)),
                )
                logger.warning(
                    "outbox publish deferred",
                    extra={"event_id": str(event.id), "error": error},
                )
            continue
        await repo.mark_published(event, when=moment)
        published += 1

    await session.commit()
    return published
