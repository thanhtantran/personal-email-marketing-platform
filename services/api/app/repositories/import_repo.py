from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImportJob, ImportRow
from app.repositories.base import TenantScopedRepository


class ImportRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, import_id: uuid.UUID) -> ImportJob | None:
        result = await self.session.execute(
            select(ImportJob).where(
                ImportJob.tenant_id == self.tenant_id, ImportJob.id == import_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> ImportJob | None:
        result = await self.session.execute(
            select(ImportJob).where(
                ImportJob.tenant_id == self.tenant_id, ImportJob.idempotency_key == key
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        uploaded_object_key: str | None,
        mapping: dict | None = None,
        idempotency_key: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> ImportJob:
        job = ImportJob(
            tenant_id=self.tenant_id,
            uploaded_object_key=uploaded_object_key,
            mapping=mapping,
            status="awaiting_upload",
            idempotency_key=idempotency_key,
            created_by=created_by,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def update(self, job: ImportJob, fields: dict) -> ImportJob:
        for key, value in fields.items():
            setattr(job, key, value)
        await self.session.flush()
        return job

    async def delete_rows(self, import_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(ImportRow).where(
                ImportRow.tenant_id == self.tenant_id, ImportRow.import_id == import_id
            )
        )
        await self.session.flush()

    async def add_rows(self, rows: list[ImportRow]) -> None:
        for row in rows:
            self.session.add(row)
        await self.session.flush()
