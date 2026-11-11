"""Tenant-scoped persistence.

Every repository that touches tenant-owned rows requires an explicit
``tenant_id`` and includes it in query filters. This is the single choke point
that keeps a Phase 1 single-owner deployment from drifting into unsafe global
queries (see SPEC.md invariant 1).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


class TenantScopedRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        if tenant_id is None:
            raise ValueError("tenant_id is required for tenant-scoped repositories")
        self.session = session
        self.tenant_id = tenant_id
