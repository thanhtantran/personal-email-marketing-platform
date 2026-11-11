"""Tenant-scoped repositories must refuse to operate without a tenant id."""

from __future__ import annotations

import uuid

import pytest

from app.repositories.base import TenantScopedRepository


def test_missing_tenant_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        TenantScopedRepository(None, None)  # type: ignore[arg-type]


def test_tenant_id_is_retained() -> None:
    tenant_id = uuid.uuid4()
    repository = TenantScopedRepository(None, tenant_id)  # type: ignore[arg-type]
    assert repository.tenant_id == tenant_id
