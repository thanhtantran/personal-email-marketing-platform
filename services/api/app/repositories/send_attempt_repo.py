"""Tenant-scoped persistence for provider submission attempts.

An attempt row is inserted (``state=pending``) **before** the network call so a
crash can never erase the knowledge that a request may have reached the provider.
``UNIQUE(recipient_id, attempt_no)`` makes an at-least-once worker converge on the
same row instead of creating a second, and local usage accounting counts rows
rather than API keys (SPEC.md invariants 3 and 6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SendAttempt
from app.repositories.base import TenantScopedRepository


class SendAttemptRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def next_attempt_no(self, recipient_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(SendAttempt.attempt_no), 0)).where(
                SendAttempt.tenant_id == self.tenant_id,
                SendAttempt.recipient_id == recipient_id,
            )
        )
        return int(result.scalar_one()) + 1

    async def create_pending(
        self,
        *,
        recipient_id: uuid.UUID,
        provider_account_id: uuid.UUID,
        attempt_no: int,
        request_digest: str,
        idempotency_key: str,
    ) -> SendAttempt:
        attempt = SendAttempt(
            tenant_id=self.tenant_id,
            recipient_id=recipient_id,
            provider_account_id=provider_account_id,
            attempt_no=attempt_no,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            state="pending",
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def record_result(
        self,
        attempt: SendAttempt,
        *,
        state: str,
        when: datetime,
        provider_message_id: str | None = None,
        error_class: str | None = None,
        response_code: int | None = None,
        unknown_reason: str | None = None,
    ) -> SendAttempt:
        attempt.state = state
        attempt.finished_at = when
        attempt.provider_message_id = provider_message_id
        attempt.error_class = error_class
        attempt.response_code = response_code
        attempt.unknown_reason = unknown_reason
        await self.session.flush()
        return attempt

    async def get(self, attempt_id: uuid.UUID) -> SendAttempt | None:
        result = await self.session.execute(
            select(SendAttempt).where(
                SendAttempt.tenant_id == self.tenant_id, SendAttempt.id == attempt_id
            )
        )
        return result.scalar_one_or_none()

    async def latest_for_recipient(self, recipient_id: uuid.UUID) -> SendAttempt | None:
        result = await self.session.execute(
            select(SendAttempt)
            .where(
                SendAttempt.tenant_id == self.tenant_id,
                SendAttempt.recipient_id == recipient_id,
            )
            .order_by(SendAttempt.attempt_no.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_recipient(self, recipient_id: uuid.UUID) -> list[SendAttempt]:
        result = await self.session.execute(
            select(SendAttempt)
            .where(
                SendAttempt.tenant_id == self.tenant_id,
                SendAttempt.recipient_id == recipient_id,
            )
            .order_by(SendAttempt.attempt_no)
        )
        return list(result.scalars().all())

    async def count_for_account_since(
        self, provider_account_id: uuid.UUID, *, since: datetime, states: tuple[str, ...]
    ) -> int:
        """Count attempts already counted against an account in a window.

        This is local accounting used with the reservation counter; it is never
        presented as a provider-confirmed quota.
        """
        stmt = (
            select(func.count())
            .select_from(SendAttempt)
            .where(
                SendAttempt.tenant_id == self.tenant_id,
                SendAttempt.provider_account_id == provider_account_id,
                SendAttempt.started_at >= since,
            )
        )
        if states:
            stmt = stmt.where(SendAttempt.state.in_(states))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())
