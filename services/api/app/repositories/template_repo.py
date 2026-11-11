"""Tenant-scoped template persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Template
from app.repositories.base import TenantScopedRepository


class TemplateRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(
        self, template_id: uuid.UUID, *, include_archived: bool = True
    ) -> Template | None:
        stmt = select(Template).where(
            Template.tenant_id == self.tenant_id, Template.id == template_id
        )
        if not include_archived:
            stmt = stmt.where(Template.status != "archived")
        return await self.session.scalar(stmt)

    async def list_active(self) -> list[Template]:
        stmt = (
            select(Template)
            .where(Template.tenant_id == self.tenant_id, Template.status != "archived")
            .order_by(Template.updated_at.desc(), Template.id.desc())
        )
        result = await self.session.scalars(stmt)
        return list(result)
