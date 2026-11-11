from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Membership


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        result = await self.session.execute(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_first_active_for_user(self, user_id: uuid.UUID) -> Membership | None:
        """Phase 1 has exactly one membership per user; Phase 2 will add selection."""
        result = await self.session.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status == "active")
            .order_by(Membership.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def ensure(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str = "owner",
        status: str = "active",
    ) -> Membership:
        existing = await self.get(tenant_id, user_id)
        if existing is not None:
            return existing
        membership = Membership(
            tenant_id=tenant_id, user_id=user_id, role=role, status=status
        )
        self.session.add(membership)
        await self.session.flush()
        return membership
