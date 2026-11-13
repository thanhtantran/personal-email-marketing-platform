"""Tenant-scoped persistence for campaigns, snapshots and the recipient ledger.

Campaign rows are always fetched with ``tenant_id`` in the filter, and state
transitions are read with ``FOR UPDATE`` so two concurrent launch/pause requests
cannot both observe the same status and advance it twice (ARCHITECTURE.md
section 7).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, CampaignRecipient, CampaignSnapshot
from app.db.models.campaign import (
    RECIPIENT_DISPATCHABLE_STATUSES,
    RECIPIENT_STATUS_ACCEPTED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_RETRY,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNKNOWN,
)
from app.repositories.base import TenantScopedRepository


class CampaignRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, campaign_id: uuid.UUID) -> Campaign | None:
        result = await self.session.execute(
            select(Campaign).where(
                Campaign.tenant_id == self.tenant_id, Campaign.id == campaign_id
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, campaign_id: uuid.UUID) -> Campaign | None:
        """Load a campaign row with a row lock for a state transition."""
        result = await self.session.execute(
            select(Campaign)
            .where(Campaign.tenant_id == self.tenant_id, Campaign.id == campaign_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        subject: str = "",
        from_name: str = "",
        from_email: str = "",
        reply_to: str | None = None,
        template_id: uuid.UUID | None = None,
        segment_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> Campaign:
        campaign = Campaign(
            tenant_id=self.tenant_id,
            name=name,
            status="draft",
            subject=subject,
            from_name=from_name,
            from_email=from_email,
            reply_to=reply_to,
            template_id=template_id,
            segment_id=segment_id,
            created_by=created_by,
        )
        self.session.add(campaign)
        await self.session.flush()
        return campaign

    async def update_fields(self, campaign: Campaign, fields: dict) -> Campaign:
        for key, value in fields.items():
            setattr(campaign, key, value)
        await self.session.flush()
        return campaign

    def _list_stmt(self, *, status: str | None) -> Select:
        stmt = select(Campaign).where(Campaign.tenant_id == self.tenant_id)
        if status:
            stmt = stmt.where(Campaign.status == status)
        return stmt

    async def list_page(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        status: str | None = None,
    ) -> list[Campaign]:
        stmt = self._list_stmt(status=status)
        if cursor:
            stmt = stmt.where(tuple_(Campaign.created_at, Campaign.id) < tuple_(*cursor))
        stmt = stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Campaign).where(
            Campaign.tenant_id == self.tenant_id
        )
        if status:
            stmt = stmt.where(Campaign.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


async def claim_due_campaigns(
    session: AsyncSession, *, now: datetime, limit: int, status: str = "scheduled"
) -> list[Campaign]:
    """Lock and return campaigns whose ``scheduled_at`` has arrived.

    This is a system-level claim across tenants, used only by the scheduler, so
    it is a module function rather than a tenant-scoped repository method.
    ``SKIP LOCKED`` lets a restarted scheduler pick up work another instance
    already holds without double-claiming it; the caller advances state and
    commits so each due campaign is claimed exactly once.
    """
    result = await session.execute(
        select(Campaign)
        .where(
            Campaign.status == status,
            Campaign.scheduled_at.is_not(None),
            Campaign.scheduled_at <= now,
        )
        .order_by(Campaign.scheduled_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


class CampaignSnapshotRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def latest(self, campaign_id: uuid.UUID) -> CampaignSnapshot | None:
        result = await self.session.execute(
            select(CampaignSnapshot)
            .where(
                CampaignSnapshot.tenant_id == self.tenant_id,
                CampaignSnapshot.campaign_id == campaign_id,
            )
            .order_by(CampaignSnapshot.snapshot_version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def next_version(self, campaign_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(CampaignSnapshot.snapshot_version), 0)).where(
                CampaignSnapshot.tenant_id == self.tenant_id,
                CampaignSnapshot.campaign_id == campaign_id,
            )
        )
        return int(result.scalar_one()) + 1

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        content: dict,
        audience_definition: dict,
        recipient_count: int,
        snapshot_version: int = 1,
    ) -> CampaignSnapshot:
        snapshot = CampaignSnapshot(
            tenant_id=self.tenant_id,
            campaign_id=campaign_id,
            snapshot_version=snapshot_version,
            content=content,
            audience_definition=audience_definition,
            recipient_count=recipient_count,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot


class CampaignRecipientRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def bulk_insert_ignore(self, rows: Sequence[dict]) -> int:
        """Insert ledger rows, ignoring any that already exist.

        Conflicts on ``(campaign_id, email_snapshot)`` or
        ``(tenant_id, idempotency_key)`` are silently skipped, so a replayed
        launch or a restarted worker cannot duplicate a recipient. Returns the
        number of rows actually inserted.
        """
        if not rows:
            return 0
        payload = [{**row, "tenant_id": self.tenant_id} for row in rows]
        stmt = (
            pg_insert(CampaignRecipient)
            .values(payload)
            .on_conflict_do_nothing()
            .returning(CampaignRecipient.id)
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def count_for_campaign(
        self, campaign_id: uuid.UUID, *, status: str | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(CampaignRecipient)
            .where(
                CampaignRecipient.tenant_id == self.tenant_id,
                CampaignRecipient.campaign_id == campaign_id,
            )
        )
        if status:
            stmt = stmt.where(CampaignRecipient.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_page(
        self,
        campaign_id: uuid.UUID,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        status: str | None = None,
    ) -> list[CampaignRecipient]:
        stmt = select(CampaignRecipient).where(
            CampaignRecipient.tenant_id == self.tenant_id,
            CampaignRecipient.campaign_id == campaign_id,
        )
        if status:
            stmt = stmt.where(CampaignRecipient.status == status)
        if cursor:
            stmt = stmt.where(
                tuple_(CampaignRecipient.created_at, CampaignRecipient.id) < tuple_(*cursor)
            )
        stmt = stmt.order_by(
            CampaignRecipient.created_at.desc(), CampaignRecipient.id.desc()
        ).limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------ dispatch
    async def get_for_update(self, recipient_id: uuid.UUID) -> CampaignRecipient | None:
        """Lock one ledger row for a submission, so two workers cannot both send."""
        result = await self.session.execute(
            select(CampaignRecipient)
            .where(
                CampaignRecipient.tenant_id == self.tenant_id,
                CampaignRecipient.id == recipient_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_dispatchable(
        self, campaign_id: uuid.UUID, *, limit: int
    ) -> list[CampaignRecipient]:
        """Recipients this campaign still owes a submission to."""
        result = await self.session.execute(
            select(CampaignRecipient)
            .where(
                CampaignRecipient.tenant_id == self.tenant_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status.in_(RECIPIENT_DISPATCHABLE_STATUSES),
            )
            .order_by(CampaignRecipient.created_at, CampaignRecipient.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def claim_due(
        self, campaign_id: uuid.UUID, *, limit: int, now: datetime
    ) -> list[CampaignRecipient]:
        """Lock recipients whose retry time has arrived, skipping locked rows."""
        result = await self.session.execute(
            select(CampaignRecipient)
            .where(
                CampaignRecipient.tenant_id == self.tenant_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status.in_(RECIPIENT_DISPATCHABLE_STATUSES),
                (CampaignRecipient.next_attempt_at.is_(None))
                | (CampaignRecipient.next_attempt_at <= now),
            )
            .order_by(CampaignRecipient.next_attempt_at, CampaignRecipient.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def earliest_due(self, campaign_id: uuid.UUID) -> datetime | None:
        """Earliest ``next_attempt_at`` among recipients still owed a submission.

        Used by the dispatch loop to schedule its next wake-up instead of
        polling. Recipients never submitted carry no time, so this returns
        ``None`` when every remaining row is due immediately.
        """
        result = await self.session.execute(
            select(func.min(CampaignRecipient.next_attempt_at)).where(
                CampaignRecipient.tenant_id == self.tenant_id,
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status.in_(RECIPIENT_DISPATCHABLE_STATUSES),
            )
        )
        return result.scalar_one_or_none()

    async def mark_accepted(
        self,
        recipient: CampaignRecipient,
        *,
        provider_account_id: uuid.UUID,
        provider_message_id: str | None,
        when: datetime,
    ) -> None:
        recipient.status = RECIPIENT_STATUS_ACCEPTED
        recipient.provider_account_id = provider_account_id
        recipient.provider_message_id = provider_message_id
        recipient.attempt_count = recipient.attempt_count + 1
        recipient.accepted_at = when
        recipient.next_attempt_at = None
        recipient.error_code = None
        await self.session.flush()

    async def mark_transient_retry(
        self,
        recipient: CampaignRecipient,
        *,
        provider_account_id: uuid.UUID | None,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        recipient.status = RECIPIENT_STATUS_RETRY
        recipient.provider_account_id = provider_account_id
        recipient.attempt_count = recipient.attempt_count + 1
        recipient.next_attempt_at = next_attempt_at
        recipient.error_code = error_code
        await self.session.flush()

    async def mark_permanent_failure(
        self,
        recipient: CampaignRecipient,
        *,
        provider_account_id: uuid.UUID,
        error_code: str | None,
        when: datetime,
    ) -> None:
        recipient.status = RECIPIENT_STATUS_FAILED
        recipient.provider_account_id = provider_account_id
        recipient.attempt_count = recipient.attempt_count + 1
        recipient.next_attempt_at = None
        recipient.outcome_at = when
        recipient.error_code = error_code
        await self.session.flush()

    async def mark_skipped(
        self, recipient: CampaignRecipient, *, error_code: str | None, when: datetime
    ) -> None:
        """Retire a recipient that failed last-minute consent/suppression checks.

        No provider call is made, so the attempt counter is deliberately left
        untouched: the recipient was never submitted.
        """
        recipient.status = RECIPIENT_STATUS_SKIPPED
        recipient.next_attempt_at = None
        recipient.outcome_at = when
        recipient.error_code = error_code
        await self.session.flush()

    async def mark_unknown(
        self,
        recipient: CampaignRecipient,
        *,
        provider_account_id: uuid.UUID,
        error_code: str | None,
        when: datetime,
    ) -> None:
        """Record an ambiguous outcome; no automatic retry is scheduled."""
        recipient.status = RECIPIENT_STATUS_UNKNOWN
        recipient.provider_account_id = provider_account_id
        recipient.attempt_count = recipient.attempt_count + 1
        recipient.next_attempt_at = None
        recipient.outcome_at = when
        recipient.error_code = error_code
        await self.session.flush()
