from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact, Segment
from app.domain.audience.consent import eligible_contact_filter
from app.domain.audience.segments import build_filter
from app.repositories.base import TenantScopedRepository


class SegmentRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, segment_id: uuid.UUID) -> Segment | None:
        result = await self.session.execute(
            select(Segment).where(
                Segment.tenant_id == self.tenant_id, Segment.id == segment_id
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Segment]:
        result = await self.session.execute(
            select(Segment)
            .where(Segment.tenant_id == self.tenant_id)
            .order_by(Segment.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, *, name: str, definition: dict) -> Segment:
        segment = Segment(tenant_id=self.tenant_id, name=name, definition=definition, version=1)
        self.session.add(segment)
        await self.session.flush()
        return segment

    async def update(self, segment: Segment, *, name: str, definition: dict) -> Segment:
        segment.name = name
        segment.definition = definition
        segment.version += 1
        await self.session.flush()
        return segment

    async def match_count(self, definition: dict) -> int:
        """Count contacts matching the AST regardless of consent/suppression."""
        result = await self.session.execute(
            select(func.count())
            .select_from(Contact)
            .where(build_filter(definition, self.tenant_id))
        )
        return int(result.scalar_one())

    async def eligible_count(self, definition: dict) -> int:
        """Count contacts that both match the AST and are eligible to be marketed to.

        Suppressed, unsubscribed, invalid and non-consented contacts are excluded,
        so an estimate can never advertise a recipient that dispatch would reject.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(Contact)
            .where(
                eligible_contact_filter(self.tenant_id),
                build_filter(definition, self.tenant_id),
            )
        )
        return int(result.scalar_one())
