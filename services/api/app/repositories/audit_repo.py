from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.repositories.base import TenantScopedRepository


class AuditRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def record(
        self,
        *,
        action: str,
        actor_user_id: uuid.UUID | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        request_id: str | None = None,
        details: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=self.tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            request_id=request_id,
            details=details,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
