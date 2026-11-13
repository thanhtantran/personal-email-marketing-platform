"""Celery tasks.

Consumers are idempotent by construction: they re-read durable state under a
row lock and no-op when the work has already been done, so at-least-once
delivery cannot double-run a step (SPEC.md invariant 8).
"""

from __future__ import annotations

import asyncio
import uuid

from app.config import get_settings
from app.db.session import SessionFactory
from app.domain.campaign.lifecycle import ensure_transition
from app.domain.events.processing import WebhookProcessingService
from app.logging import get_logger
from app.redis_client import get_redis
from app.repositories.campaign_repo import CampaignRepository
from app.storage.s3 import get_storage
from app.workers.celery_app import celery_app
from app.workers.dispatch import dispatch_campaign

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.dispatch_campaign")
def dispatch_campaign_task(
    tenant_id: str, campaign_id: str, snapshot_version: int | None = None
) -> str:
    """Advance a prepared campaign and submit its due recipients.

    The one-time ``preparing`` -> ``sending`` advance is idempotent, then the
    per-recipient submission loop runs (``app.workers.dispatch``); a later pass
    is re-enqueued by that loop when retries remain.
    """
    return asyncio.run(
        _dispatch_campaign(uuid.UUID(tenant_id), uuid.UUID(campaign_id), snapshot_version)
    )


async def _dispatch_campaign(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, snapshot_version: int | None
) -> str:
    settings = get_settings()
    async with SessionFactory() as session:
        campaigns = CampaignRepository(session, tenant_id)
        campaign = await campaigns.get_for_update(campaign_id)
        if campaign is None:
            return "missing"
        if campaign.status == "preparing":
            ensure_transition(campaign.status, "sending")
            campaign.status = "sending"
            await session.flush()
            await session.commit()
            logger.info(
                "campaign dispatch started",
                extra={
                    "campaign_id": str(campaign_id),
                    "snapshot_version": snapshot_version,
                },
            )
        elif campaign.status != "sending":
            # Duplicate delivery, or a pause/cancel that won the race: no-op.
            return campaign.status

    async with SessionFactory() as session:
        report = await dispatch_campaign(
            session,
            tenant_id,
            settings,
            campaign_id,
            snapshot_version=snapshot_version,
            redis=get_redis(),
        )
    return report.summary()


@celery_app.task(name="app.workers.tasks.process_webhook")
def process_webhook_task(tenant_id: str, webhook_event_id: str) -> str:
    """Normalize one accepted webhook delivery and apply its effects.

    Idempotent end to end: the row is re-read under a lock, inserts ignore
    conflicts and suppression is an idempotent upsert, so an outbox redelivery or
    a retried task converges on the same state (SPEC.md invariant 8).
    """
    return asyncio.run(
        _process_webhook(uuid.UUID(tenant_id), uuid.UUID(webhook_event_id))
    )


async def _process_webhook(tenant_id: uuid.UUID, webhook_event_id: uuid.UUID) -> str:
    settings = get_settings()
    async with SessionFactory() as session:
        report = await WebhookProcessingService(session, tenant_id, settings).process(
            webhook_event_id, storage=get_storage()
        )
    return report.status
