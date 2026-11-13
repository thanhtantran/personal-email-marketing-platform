"""Operator-facing provider account management.

An account is the quota, rate and routing boundary; a credential is only an
encrypted secret used to reach it. This service therefore never derives capacity
from the number of credentials, and no code path returns a secret value
(SPEC.md invariants 3 and 9).

Verification and capacity refresh call the provider through its adapter and store
the dated facts the router acts on: ``eligibility_verified_at`` and
``quota_refreshed_at`` make staleness observable, and a provider that exposes no
cap is recorded as *unknown* instead of a guessed number.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ProviderAccount, ProviderCredential, ProviderRoutingControl
from app.db.models.provider import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_DISABLED,
    ACCOUNT_STATUS_PAUSED,
    MESSAGE_CLASSES,
)
from app.domain.gateway import GatewayStatus, ProviderGateway
from app.errors import ConflictError, NotFoundError, ValidationAppError
from app.providers.contract import (
    AccountVerification,
    CapacitySnapshot,
    ProviderAdapter,
    Secret,
)
from app.providers.registry import available_providers, get_adapter, is_known_provider
from app.repositories.audit_repo import AuditRepository
from app.repositories.provider_repo import (
    ProviderAccountRepository,
    ProviderCredentialRepository,
    ProviderRoutingControlRepository,
)
from app.security.encryption import EncryptionKeyError, get_secret_box_provider

ACCOUNT_STATUSES: frozenset[str] = frozenset(
    {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_PAUSED, ACCOUNT_STATUS_DISABLED}
)


def _validate_message_classes(classes: list[str]) -> list[str]:
    unknown = set(classes) - MESSAGE_CLASSES
    if unknown:
        raise ValidationAppError(
            "Unsupported message class",
            extra={"reason": "invalid_message_class", "unknown": sorted(unknown)},
        )
    return sorted(set(classes))


def _capacity_fields(account: ProviderAccount, snapshot: CapacitySnapshot) -> tuple[dict, dict]:
    """Derive the ``limits``/``quota_state`` rows from a provider observation.

    Existing routing priority/weight are preserved; a limit the provider did not
    report is removed rather than carried over, so a stale cap can never look
    fresh. Missing limits leave capacity *unknown*, which blocks routing.
    """
    limits = dict(account.limits or {})
    for key, value in (
        ("daily_limit", snapshot.daily_limit),
        ("monthly_limit", snapshot.monthly_limit),
        ("rate_per_second", snapshot.rate_per_second),
    ):
        if value is None:
            limits.pop(key, None)
        else:
            limits[key] = value

    moment = snapshot.observed_at.astimezone(UTC)
    state = {
        "period_day": moment.date().isoformat(),
        "period_month": f"{moment.year:04d}-{moment.month:02d}",
        "daily_used": snapshot.daily_used or 0,
        "monthly_used": snapshot.monthly_used or 0,
    }
    return limits, state


class ProviderAccountService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, settings: Settings) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.accounts = ProviderAccountRepository(session, tenant_id)
        self.credentials = ProviderCredentialRepository(session, tenant_id)
        self.controls = ProviderRoutingControlRepository(session, tenant_id)
        self.audit = AuditRepository(session, tenant_id)
        self.gateway = ProviderGateway(session, tenant_id, settings)

    # --------------------------------------------------------------- accounts
    async def list_page(
        self, *, limit: int, cursor: tuple[datetime, uuid.UUID] | None = None, status: str | None
    ) -> list[ProviderAccount]:
        return await self.accounts.list_page(limit=limit, cursor=cursor, status=status)

    async def count(self, *, status: str | None = None) -> int:
        return await self.accounts.count(status=status)

    async def get(self, account_id: uuid.UUID) -> ProviderAccount:
        account = await self.accounts.get(account_id)
        if account is None:
            raise NotFoundError("Provider account not found")
        return account

    async def get_with_credentials(
        self, account_id: uuid.UUID
    ) -> tuple[ProviderAccount, list[ProviderCredential]]:
        account = await self.get(account_id)
        return account, await self.credentials.list_for_account(account.id)

    async def create(
        self,
        *,
        provider: str,
        external_account_ref: str,
        display_name: str = "",
        eligible_message_classes: list[str] | None = None,
        sender_domains: list[str] | None = None,
        routing_priority: int | None = None,
        routing_weight: int | None = None,
        secret: str,
        secret_label: str = "",
    ) -> ProviderAccount:
        """Create an account and its first credential in one transaction."""
        if not is_known_provider(provider):
            raise ValidationAppError(
                "Unknown provider",
                extra={
                    "reason": "unknown_provider",
                    "provider": provider,
                    "known": available_providers(),
                },
            )
        existing = await self.accounts.get_by_external_ref(provider, external_account_ref)
        if existing is not None:
            raise ConflictError(
                "Provider account already exists",
                extra={"reason": "provider_account_exists", "account_id": str(existing.id)},
            )
        classes = _validate_message_classes(eligible_message_classes or [])

        limits: dict = {}
        if routing_priority is not None:
            limits["routing_priority"] = routing_priority
        if routing_weight is not None:
            limits["routing_weight"] = routing_weight

        account = await self.accounts.create(
            provider=provider,
            external_account_ref=external_account_ref,
            display_name=display_name,
            eligible_message_classes=classes,
            sender_domains=list(sender_domains or []),
            limits=limits,
        )
        await self.add_credential(account.id, secret=secret, label=secret_label)
        await self.audit.record(
            action="provider.account_created",
            object_type="provider_account",
            object_id=str(account.id),
            details={"provider": provider, "external_account_ref": external_account_ref},
        )
        return account

    async def update(self, account_id: uuid.UUID, *, fields: dict) -> ProviderAccount:
        account = await self.get(account_id)
        updates: dict = {}
        if fields.get("display_name") is not None:
            updates["display_name"] = fields["display_name"]
        if fields.get("status") is not None:
            if fields["status"] not in ACCOUNT_STATUSES:
                raise ValidationAppError(
                    "Unsupported account status",
                    extra={"reason": "invalid_status", "allowed": sorted(ACCOUNT_STATUSES)},
                )
            updates["status"] = fields["status"]
        if fields.get("eligible_message_classes") is not None:
            updates["eligible_message_classes"] = _validate_message_classes(
                fields["eligible_message_classes"]
            )
        if fields.get("sender_domains") is not None:
            updates["sender_domains"] = list(fields["sender_domains"])

        limits = dict(account.limits or {})
        for key in ("routing_priority", "routing_weight"):
            if fields.get(key) is not None:
                limits[key] = int(fields[key])
        if limits != (account.limits or {}):
            updates["limits"] = limits

        if not updates:
            return account
        await self.accounts.update_fields(account, updates)
        await self.audit.record(
            action="provider.account_updated",
            object_type="provider_account",
            object_id=str(account.id),
            details={"fields": sorted(updates)},
        )
        return account

    # ------------------------------------------------------------ credentials
    async def add_credential(
        self, account_id: uuid.UUID, *, secret: str, label: str = ""
    ) -> ProviderCredential:
        account = await self.get(account_id)
        box = get_secret_box_provider().active
        credential = await self.credentials.create(
            provider_account_id=account.id,
            secret_ciphertext=box.encrypt(secret),
            key_version=box.key_version,
            label=label,
        )
        await self.audit.record(
            action="provider.credential_added",
            object_type="provider_account",
            object_id=str(account.id),
            details={"credential_id": str(credential.id), "label": label},
        )
        return credential

    async def revoke_credential(
        self, account_id: uuid.UUID, credential_id: uuid.UUID, *, when: datetime | None = None
    ) -> ProviderCredential:
        account = await self.get(account_id)
        credential = await self.credentials.get(credential_id)
        if credential is None or credential.provider_account_id != account.id:
            raise NotFoundError("Provider credential not found")
        await self.credentials.revoke(credential, when=when or datetime.now(UTC))
        await self.audit.record(
            action="provider.credential_revoked",
            object_type="provider_account",
            object_id=str(account.id),
            details={"credential_id": str(credential.id)},
        )
        return credential

    # ------------------------------------------------- verify / refresh facts
    async def verify(
        self, account_id: uuid.UUID, *, now: datetime | None = None
    ) -> tuple[ProviderAccount, AccountVerification]:
        """Confirm the account with its provider and record the dated facts."""
        account = await self.get(account_id)
        adapter = self._adapter(account)
        secret = await self._secret_for(account)
        moment = now or datetime.now(UTC)
        verification = await adapter.verify_account(secret, account.external_account_ref)

        updates: dict = {"health_state": verification.health_state}
        if verification.sender_domains:
            updates["sender_domains"] = list(verification.sender_domains)
        if verification.eligible_message_classes:
            updates["eligible_message_classes"] = _validate_message_classes(
                sorted(verification.eligible_message_classes)
            )
        if verification.valid:
            # Only a successful verification refreshes the eligibility timestamp;
            # a failed one must leave the previous observation age visible.
            updates["eligibility_verified_at"] = moment
        await self.accounts.update_fields(account, updates)
        await self.audit.record(
            action="provider.account_verified",
            object_type="provider_account",
            object_id=str(account.id),
            details={
                "provider": account.provider,
                "valid": verification.valid,
                "health_state": verification.health_state,
                "observed_by": verification.observed_by,
                "at": moment.isoformat(),
            },
        )
        return account, verification

    async def refresh_capacity(
        self, account_id: uuid.UUID, *, now: datetime | None = None
    ) -> tuple[ProviderAccount, CapacitySnapshot]:
        """Store the provider's capacity facts, dated, for the router to act on."""
        account = await self.get(account_id)
        adapter = self._adapter(account)
        secret = await self._secret_for(account)
        snapshot = await adapter.refresh_capacity(secret)
        limits, state = _capacity_fields(account, snapshot)
        await self.accounts.update_fields(
            account,
            {
                "limits": limits,
                "quota_state": state,
                "quota_refreshed_at": snapshot.observed_at,
            },
        )
        await self.audit.record(
            action="provider.capacity_refreshed",
            object_type="provider_account",
            object_id=str(account.id),
            details={
                "provider": account.provider,
                "source": snapshot.source,
                "daily_limit": snapshot.daily_limit,
                "monthly_limit": snapshot.monthly_limit,
                "observed_at": snapshot.observed_at.isoformat(),
            },
        )
        return account, snapshot

    # ---------------------------------------------------------------- routing
    async def routing_status(self) -> GatewayStatus:
        return await self.gateway.status()

    async def set_paused(
        self,
        *,
        paused: bool,
        reason: str | None,
        actor_user_id: uuid.UUID | None,
    ) -> ProviderRoutingControl:
        control = await self.controls.set_paused(
            paused=paused, reason=reason, actor_user_id=actor_user_id
        )
        await self.audit.record(
            action="provider.routing_paused" if paused else "provider.routing_resumed",
            actor_user_id=actor_user_id,
            object_type="provider_routing_control",
            object_id=str(control.id),
            details={"reason": reason} if paused else {},
        )
        return control

    # ---------------------------------------------------------------- helpers
    def _adapter(self, account: ProviderAccount) -> ProviderAdapter:
        try:
            return get_adapter(account.provider, settings=self.settings)
        except Exception as exc:  # noqa: BLE001 - surface an actionable 422
            raise ValidationAppError(
                "No adapter is registered for this provider",
                extra={"reason": "unknown_provider", "provider": account.provider},
            ) from exc

    async def _secret_for(self, account: ProviderAccount) -> Secret:
        credential = await self.credentials.get_active_for_account(account.id)
        if credential is None:
            raise ValidationAppError(
                "Account has no active credential",
                extra={"reason": "credential_unavailable", "account_id": str(account.id)},
            )
        try:
            box = get_secret_box_provider().box_for(credential.key_version)
            value = box.decrypt(credential.secret_ciphertext)
        except EncryptionKeyError as exc:
            raise ValidationAppError(
                "Credential could not be decrypted",
                extra={"reason": "credential_unavailable", "account_id": str(account.id)},
            ) from exc
        return Secret(value, label=credential.label)
