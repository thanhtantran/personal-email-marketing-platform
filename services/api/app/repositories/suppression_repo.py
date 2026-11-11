from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Suppression
from app.repositories.base import TenantScopedRepository


class SuppressionRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, normalized_email: str, reason: str) -> Suppression | None:
        result = await self.session.execute(
            select(Suppression).where(
                Suppression.tenant_id == self.tenant_id,
                Suppression.normalized_email == normalized_email,
                Suppression.reason == reason,
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, normalized_email: str) -> bool:
        result = await self.session.execute(
            select(Suppression.id)
            .where(
                Suppression.tenant_id == self.tenant_id,
                Suppression.normalized_email == normalized_email,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def active_emails(self, emails: Iterable[str]) -> set[str]:
        values = list(emails)
        if not values:
            return set()
        result = await self.session.execute(
            select(Suppression.normalized_email).where(
                Suppression.tenant_id == self.tenant_id,
                Suppression.normalized_email.in_(values),
            )
        )
        return set(result.scalars().all())

    async def list_for_email(self, normalized_email: str) -> list[Suppression]:
        result = await self.session.execute(
            select(Suppression)
            .where(
                Suppression.tenant_id == self.tenant_id,
                Suppression.normalized_email == normalized_email,
            )
            .order_by(Suppression.occurred_at.desc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        normalized_email: str,
        reason: str,
        source: str | None = None,
        occurred_at: datetime | None = None,
        expires_at: datetime | None = None,
        evidence: dict | None = None,
    ) -> Suppression:
        """Idempotently record a suppression.

        Repeated events (duplicate webhooks, replayed unsubscribe) must not create
        duplicate suppressions or reset the original occurrence time.
        """
        existing = await self.get(normalized_email, reason)
        if existing is not None:
            return existing
        record = Suppression(
            tenant_id=self.tenant_id,
            normalized_email=normalized_email,
            reason=reason,
            source=source,
            occurred_at=occurred_at or datetime.now(UTC),
            expires_at=expires_at,
            evidence=evidence,
        )
        self.session.add(record)
        await self.session.flush()
        return record
