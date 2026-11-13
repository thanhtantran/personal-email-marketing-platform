"""Transactional outbox persistence.

The outbox is the bridge between a database commit and a queue publish. A row
is written in the same transaction as the state change that produced the work,
so the two can never diverge. Unlike business tables, claiming is a
system-level operation across tenants, so this repository is not tenant-scoped;
``tenant_id`` is carried on every row and on the published envelope.

``dedupe_key`` (unique per tenant) makes enqueue idempotent: replaying a launch
or re-running a scheduler pass cannot create a second copy of the same work.
See ARCHITECTURE.md section 7.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent

STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict,
        dedupe_key: str | None = None,
        available_at: datetime | None = None,
    ) -> bool:
        """Enqueue work idempotently.

        Returns ``True`` when a row was inserted and ``False`` when an event
        with the same ``(tenant_id, dedupe_key)`` already existed.
        """
        values = {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "payload": payload,
            "status": STATUS_PENDING,
            "attempts": 0,
            "dedupe_key": dedupe_key,
        }
        if available_at is not None:
            values["available_at"] = available_at
        stmt = (
            pg_insert(OutboxEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_key"])
            .returning(OutboxEvent.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def claim_due(self, *, now: datetime, limit: int) -> list[OutboxEvent]:
        """Lock and return pending events ready to publish.

        ``SKIP LOCKED`` lets multiple dispatchers run safely: each claims a
        disjoint set of rows and holds its lock until commit.
        """
        result = await self.session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == STATUS_PENDING,
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def mark_published(self, event: OutboxEvent, *, when: datetime) -> None:
        event.status = STATUS_PUBLISHED
        event.published_at = when
        event.last_error = None
        await self.session.flush()

    async def schedule_retry(
        self, event: OutboxEvent, *, error: str, retry_at: datetime
    ) -> None:
        event.attempts = event.attempts + 1
        event.last_error = error[:255]
        event.available_at = retry_at
        await self.session.flush()

    async def mark_failed(self, event: OutboxEvent, *, error: str) -> None:
        event.status = STATUS_FAILED
        event.attempts = event.attempts + 1
        event.last_error = error[:255]
        await self.session.flush()
