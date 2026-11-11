from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant


class TenantRepository:
    """Bootstrap-level repository. Tenants are the ownership boundary itself, so
    this repository is intentionally not tenant-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self.session.get(Tenant, tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def create(self, *, slug: str, name: str) -> Tenant:
        tenant = Tenant(slug=slug, name=name, status="active")
        self.session.add(tenant)
        await self.session.flush()
        return tenant
