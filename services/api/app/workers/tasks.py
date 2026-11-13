"""Celery tasks.

Consumers are idempotent by construction: they re-read durable state under a
row lock and no-op when the work has already been done, so at-least-once
delivery cannot double-run a step (SPEC.md invariant 8).
"""

from __future__ import annotations

import asyncio
import uuid

from app.db.session import SessionFactory
from app.domain.campaign.lifecycle import ensure_transition
from app.logging import get_logger
from app.repositories.campaign_repo import CampaignRepository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.dispatch_campaign")
def dispatch_campaign(
    tenant_id: str, campaign_id: str, snapshot_version: int | None = None
) -> str:
    """Advance a prepared campaign from ``preparing`` to ``sending``.

    Per-recipient submission is added by the provider gateway in Stage 5; this
    task owns the one-time state advance and must not repeat it.
    """
    return asyncio.run(
        _dispatch_campaign(uuid.UUID(tenant_id), uuid.UUID(campaign_id), snapshot_version)
    )


async def _dispatch_campaign(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, snapshot_version: int | None
) -> str:
    async with SessionFactory() as session:
        campaigns = CampaignRepository(session, tenant_id)
        campaign = await campaigns.get_for_update(campaign_id)
        if campaign is None:
            return "missing"
        if campaign.status != "preparing":
            # Duplicate delivery, or a pause/cancel that won the race: no-op.
            return campaign.status
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
        return "sending"
