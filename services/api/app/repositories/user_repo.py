from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_subject(self, google_subject: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.google_subject == google_subject)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        google_subject: str,
        email: str,
        display_name: str | None = None,
    ) -> User:
        user = User(
            google_subject=google_subject,
            email=email,
            display_name=display_name,
            status="active",
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_last_login(self, user: User, when: datetime | None = None) -> None:
        user.last_login_at = when or datetime.now(UTC)
        await self.session.flush()
