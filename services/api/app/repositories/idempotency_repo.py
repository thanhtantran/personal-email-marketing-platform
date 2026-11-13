"""Tenant-scoped ``Idempotency-Key`` bookkeeping.

A client-supplied key is stored with the hash of the request it first
authorized and the id of the object that request produced. A retry with the
same body returns that object; a retry that reuses the key with a different
body is a conflict and must not silently perform a different operation
(SPEC.md section 4).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyKey
from app.repositories.base import TenantScopedRepository


class IdempotencyRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, scope: str, key: str) -> IdempotencyKey | None:
        result = await self.session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == self.tenant_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def reserve(
        self, *, scope: str, key: str, request_hash: str
    ) -> tuple[IdempotencyKey, bool]:
        """Insert the key if absent; return the row and whether it was created.

        ``ON CONFLICT DO NOTHING`` makes two concurrent first requests converge
        on a single row rather than one raising a uniqueness error.
        """
        stmt = (
            pg_insert(IdempotencyKey)
            .values(
                tenant_id=self.tenant_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "scope", "key"])
            .returning(IdempotencyKey.id)
        )
        result = await self.session.execute(stmt)
        created = result.scalar_one_or_none() is not None
        record = await self.get(scope, key)
        assert record is not None  # noqa: S101 - invariant: we just inserted or it existed
        return record, created

    async def attach_object(self, record: IdempotencyKey, object_id: uuid.UUID) -> None:
        record.object_id = object_id
        await self.session.flush()
