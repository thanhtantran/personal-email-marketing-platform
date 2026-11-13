"""Scrape-time gauges read from PostgreSQL.

In-process counters answer "how much has happened since the process started".
The numbers an operator needs *right now* -- queue depth and age, ledger states,
webhook lag, account health -- are derived facts that only the durable store
knows, so they are read at scrape time rather than maintained in memory where a
restart would silently zero them (SPEC.md section 10).

A scrape never fails because the database is unreachable: that is exactly when
the rest of the exposition is most useful. The failure is counted in
``email_platform_metrics_collection_errors_total`` and the affected gauges are
left as they were, so a stale reading can never be mistaken for a fresh zero.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent, ProviderAccount, WebhookEvent
from app.db.models.campaign import CampaignRecipient
from app.db.models.event import WEBHOOK_STATUS_RECEIVED
from app.db.session import SessionFactory
from app.logging import get_logger
from app.observability.metrics import (
    CAMPAIGN_RECIPIENTS,
    METRICS_ERRORS,
    OUTBOX_EVENTS,
    OUTBOX_OLDEST_PENDING_AGE,
    PROVIDER_ACCOUNTS,
    WEBHOOK_EVENTS,
    WEBHOOK_OLDEST_UNPROCESSED_AGE,
)
from app.repositories.outbox_repo import STATUS_PENDING

logger = get_logger(__name__)

UNKNOWN = "unknown"


def _age_seconds(when: datetime | None, now: datetime) -> float | None:
    if when is None:
        return None
    moment = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    return max((now - moment).total_seconds(), 0.0)


async def _count_by(session: AsyncSession, column: ColumnElement[str]) -> dict[str, int]:
    result = await session.execute(select(column, func.count()).group_by(column))
    return {(row[0] if row[0] is not None else UNKNOWN): int(row[1]) for row in result.all()}


async def collect_queue_metrics(session: AsyncSession, *, now: datetime) -> None:
    """Outbox depth and age: the queue signal that precedes a stalled campaign."""
    counts = await _count_by(session, OutboxEvent.status)
    OUTBOX_EVENTS.clear()
    for status, count in counts.items():
        OUTBOX_EVENTS.set(float(count), status=status)

    oldest = (
        await session.execute(
            select(func.min(OutboxEvent.available_at)).where(OutboxEvent.status == STATUS_PENDING)
        )
    ).scalar_one()
    age = _age_seconds(oldest, now)
    if age is not None:
        OUTBOX_OLDEST_PENDING_AGE.set(age)


async def collect_ledger_metrics(session: AsyncSession) -> None:
    """Recipient states, so ``queued``/``unknown`` backlogs are visible."""
    counts = await _count_by(session, CampaignRecipient.status)
    CAMPAIGN_RECIPIENTS.clear()
    for status, count in counts.items():
        CAMPAIGN_RECIPIENTS.set(float(count), status=status)


async def collect_webhook_metrics(session: AsyncSession, *, now: datetime) -> None:
    """Webhook lag: accepted deliveries still waiting for normalization."""
    counts = await _count_by(session, WebhookEvent.status)
    WEBHOOK_EVENTS.clear()
    for status, count in counts.items():
        WEBHOOK_EVENTS.set(float(count), status=status)

    oldest = (
        await session.execute(
            select(func.min(WebhookEvent.created_at)).where(
                WebhookEvent.status == WEBHOOK_STATUS_RECEIVED
            )
        )
    ).scalar_one()
    age = _age_seconds(oldest, now)
    if age is not None:
        WEBHOOK_OLDEST_UNPROCESSED_AGE.set(age)


async def collect_account_metrics(session: AsyncSession) -> None:
    """Accounts by status and health: capacity that routing can actually use."""
    result = await session.execute(
        select(ProviderAccount.status, ProviderAccount.health_state, func.count()).group_by(
            ProviderAccount.status, ProviderAccount.health_state
        )
    )
    PROVIDER_ACCOUNTS.clear()
    for status, health_state, count in result.all():
        PROVIDER_ACCOUNTS.set(
            float(count),
            status=status or UNKNOWN,
            health_state=health_state or UNKNOWN,
        )


async def collect_scrape_metrics(*, now: datetime | None = None) -> None:
    """Refresh every scrape-time gauge; never raises."""
    moment = now or datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            await collect_queue_metrics(session, now=moment)
            await collect_ledger_metrics(session)
            await collect_webhook_metrics(session, now=moment)
            await collect_account_metrics(session)
    except Exception as exc:  # noqa: BLE001 - a scrape must survive a down database
        METRICS_ERRORS.inc()
        logger.warning("metrics collection failed", extra={"error": type(exc).__name__})
