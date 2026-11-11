from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> AuthSession:
        record = AuthSession(
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_active_by_hash(self, token_hash: str) -> AuthSession | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(AuthSession).where(
                AuthSession.token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, record: AuthSession, when: datetime | None = None) -> None:
        record.revoked_at = when or datetime.now(UTC)
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
        )
        now = datetime.now(UTC)
        for record in result.scalars().all():
            record.revoked_at = now
        await self.session.flush()
