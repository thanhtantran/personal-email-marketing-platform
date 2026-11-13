"""Tenant-scoped persistence for provider accounts, credentials and routing.

Accounts are the quota/rate/routing boundary; credentials are only encrypted
secrets used to reach them. Every read filters on ``tenant_id`` and quota
mutation reads the account row with ``FOR UPDATE`` so two workers cannot
over-reserve the same account in the local accounting (SPEC.md invariant 3).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderAccount, ProviderCredential, ProviderRoutingControl
from app.db.models.provider import (
    ACCOUNT_STATUS_ACTIVE,
    CREDENTIAL_STATUS_ACTIVE,
    MESSAGE_CLASS_MARKETING,
)
from app.repositories.base import TenantScopedRepository


class ProviderAccountRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, account_id: uuid.UUID) -> ProviderAccount | None:
        result = await self.session.execute(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == self.tenant_id, ProviderAccount.id == account_id
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, account_id: uuid.UUID) -> ProviderAccount | None:
        """Lock an account row for an atomic quota reservation or verification."""
        result = await self.session.execute(
            select(ProviderAccount)
            .where(
                ProviderAccount.tenant_id == self.tenant_id, ProviderAccount.id == account_id
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_external_ref(
        self, provider: str, external_account_ref: str
    ) -> ProviderAccount | None:
        result = await self.session.execute(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == self.tenant_id,
                ProviderAccount.provider == provider,
                ProviderAccount.external_account_ref == external_account_ref,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        provider: str,
        external_account_ref: str,
        display_name: str = "",
        eligible_message_classes: Sequence[str] = (),
        sender_domains: Sequence[str] = (),
        limits: dict | None = None,
    ) -> ProviderAccount:
        account = ProviderAccount(
            tenant_id=self.tenant_id,
            provider=provider,
            external_account_ref=external_account_ref,
            display_name=display_name,
            status=ACCOUNT_STATUS_ACTIVE,
            eligible_message_classes=list(eligible_message_classes),
            sender_domains=list(sender_domains),
            quota_state={},
            limits=limits or {},
            health_state="unknown",
        )
        self.session.add(account)
        await self.session.flush()
        return account

    def _list_stmt(self, *, status: str | None) -> Select:
        stmt = select(ProviderAccount).where(ProviderAccount.tenant_id == self.tenant_id)
        if status:
            stmt = stmt.where(ProviderAccount.status == status)
        return stmt

    async def list_page(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        status: str | None = None,
    ) -> list[ProviderAccount]:
        stmt = self._list_stmt(status=status)
        if cursor:
            stmt = stmt.where(
                tuple_(ProviderAccount.created_at, ProviderAccount.id) < tuple_(*cursor)
            )
        stmt = stmt.order_by(ProviderAccount.created_at.desc(), ProviderAccount.id.desc()).limit(
            limit + 1
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(ProviderAccount).where(
            ProviderAccount.tenant_id == self.tenant_id
        )
        if status:
            stmt = stmt.where(ProviderAccount.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_marketing_candidates(self) -> list[ProviderAccount]:
        """Return accounts that declare marketing eligibility.

        Freshness, health, rate and remaining quota are evaluated by the gateway;
        this query only narrows to rows that could legally carry marketing mail.
        """
        result = await self.session.execute(
            select(ProviderAccount).where(
                ProviderAccount.tenant_id == self.tenant_id,
                ProviderAccount.status == ACCOUNT_STATUS_ACTIVE,
                ProviderAccount.eligible_message_classes.any(MESSAGE_CLASS_MARKETING),
            )
        )
        return list(result.scalars().all())

    async def update_fields(self, account: ProviderAccount, fields: dict) -> ProviderAccount:
        for key, value in fields.items():
            setattr(account, key, value)
        await self.session.flush()
        return account


class ProviderCredentialRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def create(
        self,
        *,
        provider_account_id: uuid.UUID,
        secret_ciphertext: str,
        key_version: int,
        label: str = "",
    ) -> ProviderCredential:
        credential = ProviderCredential(
            tenant_id=self.tenant_id,
            provider_account_id=provider_account_id,
            secret_ciphertext=secret_ciphertext,
            key_version=key_version,
            label=label,
            status=CREDENTIAL_STATUS_ACTIVE,
        )
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def get(self, credential_id: uuid.UUID) -> ProviderCredential | None:
        result = await self.session.execute(
            select(ProviderCredential).where(
                ProviderCredential.tenant_id == self.tenant_id,
                ProviderCredential.id == credential_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_account(self, provider_account_id: uuid.UUID) -> list[ProviderCredential]:
        result = await self.session.execute(
            select(ProviderCredential)
            .where(
                ProviderCredential.tenant_id == self.tenant_id,
                ProviderCredential.provider_account_id == provider_account_id,
            )
            .order_by(ProviderCredential.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_for_account(
        self, provider_account_id: uuid.UUID
    ) -> ProviderCredential | None:
        """The most recent active credential, used for the next send.

        Rotating a credential changes this reference only; it never changes the
        account's quota (SPEC.md invariant 3).
        """
        result = await self.session.execute(
            select(ProviderCredential)
            .where(
                ProviderCredential.tenant_id == self.tenant_id,
                ProviderCredential.provider_account_id == provider_account_id,
                ProviderCredential.status == CREDENTIAL_STATUS_ACTIVE,
            )
            .order_by(ProviderCredential.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def revoke(self, credential: ProviderCredential, *, when: datetime) -> None:
        credential.status = "revoked"
        credential.rotated_at = when
        await self.session.flush()


class ProviderRoutingControlRepository(TenantScopedRepository):
    """Tenant-level routing switches (global marketing pause)."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self) -> ProviderRoutingControl | None:
        result = await self.session.execute(
            select(ProviderRoutingControl).where(
                ProviderRoutingControl.tenant_id == self.tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(self) -> ProviderRoutingControl:
        control = await self.get()
        if control is not None:
            return control
        control = ProviderRoutingControl(tenant_id=self.tenant_id, marketing_paused=False)
        self.session.add(control)
        await self.session.flush()
        return control

    async def set_paused(
        self,
        *,
        paused: bool,
        reason: str | None,
        actor_user_id: uuid.UUID | None,
    ) -> ProviderRoutingControl:
        control = await self.get_or_create()
        control.marketing_paused = paused
        control.paused_reason = reason if paused else None
        control.paused_by = actor_user_id if paused else None
        control.paused_at = datetime.now(UTC) if paused else None
        await self.session.flush()
        return control


async def get_account_by_webhook_public_id(
    session: AsyncSession, *, provider: str, public_id: uuid.UUID
) -> ProviderAccount | None:
    """Resolve a webhook target without a tenant context.

    The webhook route is public and unauthenticated, so the account is found by
    its unguessable public handle and the tenant is read *from* that row rather
    than trusted from the request (SPEC.md section 8). Signature verification
    still runs before any durable write.
    """
    result = await session.execute(
        select(ProviderAccount).where(
            ProviderAccount.provider == provider,
            ProviderAccount.webhook_public_id == public_id,
        )
    )
    return result.scalar_one_or_none()
