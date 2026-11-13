"""Tenant-scoped persistence for webhook intake and normalized events.

Both tables are append-only from the platform's point of view: a webhook row is
accepted once and then only marked processed, and a message event is inserted
once and never updated. Insertion uses ``ON CONFLICT DO NOTHING`` so a duplicate
delivery, a replayed task or a retried worker converges on the existing row
instead of creating a second one (SPEC.md sections 7 and 8).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageEvent, WebhookEvent
from app.repositories.base import TenantScopedRepository


class WebhookEventRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def add_ignore(
        self,
        *,
        provider_account_id: uuid.UUID,
        provider_event_id: str,
        event_type: str,
        occurred_at: datetime | None,
        payload_digest: str,
        payload_object_key: str | None = None,
    ) -> uuid.UUID | None:
        """Record a verified delivery, returning ``None`` when it is a replay.

        The caller must treat ``None`` as "already accepted" and do no further
        work: a replayed or forged webhook can therefore never move analytics or
        suppression state a second time.
        """
        stmt = (
            pg_insert(WebhookEvent)
            .values(
                tenant_id=self.tenant_id,
                provider_account_id=provider_account_id,
                provider_event_id=provider_event_id,
                event_type=event_type[:64],
                occurred_at=occurred_at,
                payload_digest=payload_digest,
                payload_object_key=payload_object_key,
                status="received",
            )
            .on_conflict_do_nothing(index_elements=["provider_account_id", "provider_event_id"])
            .returning(WebhookEvent.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get(self, webhook_event_id: uuid.UUID) -> WebhookEvent | None:
        result = await self.session.execute(
            select(WebhookEvent).where(
                WebhookEvent.tenant_id == self.tenant_id, WebhookEvent.id == webhook_event_id
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, webhook_event_id: uuid.UUID) -> WebhookEvent | None:
        result = await self.session.execute(
            select(WebhookEvent)
            .where(WebhookEvent.tenant_id == self.tenant_id, WebhookEvent.id == webhook_event_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_processed(self, event: WebhookEvent, *, when: datetime, status: str) -> None:
        event.status = status
        event.processed_at = when
        await self.session.flush()


class MessageEventRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def add_ignore(
        self,
        *,
        campaign_id: uuid.UUID,
        recipient_id: uuid.UUID,
        provider_account_id: uuid.UUID,
        event_type: str,
        event_key: str,
        occurred_at: datetime,
        source: str,
        metadata: dict | None = None,
    ) -> bool:
        """Insert one normalized event, returning ``False`` when it is a duplicate."""
        stmt = (
            pg_insert(MessageEvent)
            .values(
                tenant_id=self.tenant_id,
                campaign_id=campaign_id,
                recipient_id=recipient_id,
                provider_account_id=provider_account_id,
                event_type=event_type,
                event_key=event_key,
                occurred_at=occurred_at,
                source=source,
                metadata=metadata or {},
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "event_key"])
            .returning(MessageEvent.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[MessageEvent]:
        result = await self.session.execute(
            select(MessageEvent)
            .where(
                MessageEvent.tenant_id == self.tenant_id,
                MessageEvent.campaign_id == campaign_id,
            )
            .order_by(MessageEvent.occurred_at, MessageEvent.id)
        )
        return list(result.scalars().all())

    async def list_for_recipient(self, recipient_id: uuid.UUID) -> list[MessageEvent]:
        result = await self.session.execute(
            select(MessageEvent)
            .where(
                MessageEvent.tenant_id == self.tenant_id,
                MessageEvent.recipient_id == recipient_id,
            )
            .order_by(MessageEvent.occurred_at, MessageEvent.id)
        )
        return list(result.scalars().all())

    async def counts_by_type(self, campaign_id: uuid.UUID) -> dict[str, int]:
        """Total normalized events per type (duplicates already collapsed)."""
        result = await self.session.execute(
            select(MessageEvent.event_type, func.count())
            .where(
                MessageEvent.tenant_id == self.tenant_id,
                MessageEvent.campaign_id == campaign_id,
            )
            .group_by(MessageEvent.event_type)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def count_distinct_recipients(
        self, campaign_id: uuid.UUID, *, event_type: str
    ) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(MessageEvent.recipient_id))).where(
                MessageEvent.tenant_id == self.tenant_id,
                MessageEvent.campaign_id == campaign_id,
                MessageEvent.event_type == event_type,
            )
        )
        return int(result.scalar_one())

    async def count_distinct_recipients_for_types(
        self, campaign_id: uuid.UUID, *, event_types: Iterable[str]
    ) -> int:
        """Distinct recipients that produced any of ``event_types``.

        Used where analytics needs a union (for example "bounced" across hard and
        soft) so one recipient is never counted twice.
        """
        values = list(event_types)
        if not values:
            return 0
        result = await self.session.execute(
            select(func.count(func.distinct(MessageEvent.recipient_id))).where(
                MessageEvent.tenant_id == self.tenant_id,
                MessageEvent.campaign_id == campaign_id,
                MessageEvent.event_type.in_(values),
            )
        )
        return int(result.scalar_one())
