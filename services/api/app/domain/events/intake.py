"""Provider webhook intake: verify, retain, accept, enqueue.

The order of operations *is* the security property (SPEC.md section 8): the
signature and its timestamp are checked against the raw body before any durable
write, so a forged or replayed delivery can neither be accepted nor influence
analytics or suppression state. Only a verified delivery is written as a durable
``webhook_events`` row and queued for normalization; the raw body is retained
out-of-band and TTL-bound, and the row keeps just its digest, so the database
never accumulates provider PII.

If the payload cannot be retained the request fails closed (503) rather than
being acknowledged and lost: the provider's own retry then becomes the recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import ProviderAccount
from app.errors import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.providers.contract import NormalizedProviderEvent, ProviderAdapter, Secret
from app.providers.registry import get_adapter
from app.repositories.event_repo import WebhookEventRepository
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.provider_repo import get_account_by_webhook_public_id
from app.security.encryption import EncryptionKeyError, get_secret_box_provider
from app.storage.base import ObjectStorage

#: Outbox event type for asynchronous normalization of an accepted delivery.
WEBHOOK_OUTBOX_EVENT = "webhook.process"

#: Reject an oversized body before any work is done. A provider event is small;
#: a larger body is either a mistake or an attempt to exhaust memory.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


@dataclass(frozen=True)
class WebhookAcceptance:
    webhook_event_id: uuid.UUID | None
    duplicate: bool
    provider_event_id: str
    event_type: str


class WebhookIntakeService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def accept(
        self,
        *,
        provider: str,
        account_public_id: uuid.UUID,
        headers: Mapping[str, str],
        body: bytes,
        storage: ObjectStorage,
    ) -> WebhookAcceptance:
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise ValidationAppError(
                "Webhook payload is too large", extra={"reason": "payload_too_large"}
            )

        account = await get_account_by_webhook_public_id(
            self.session, provider=provider, public_id=account_public_id
        )
        if account is None:
            raise NotFoundError("Unknown webhook target")

        adapter = self._adapter(account)
        secret = self._webhook_secret(account)
        if not adapter.verify_webhook(headers, body, secret):
            raise ForbiddenError("Webhook signature verification failed")

        digest = hashlib.sha256(body).hexdigest()
        normalized = self._normalize(adapter, body)
        first = normalized[0] if normalized else None
        provider_event_id = (
            first.provider_event_id if first and first.provider_event_id else f"digest:{digest}"
        )
        event_type = first.event_type if first else ""
        object_key = await self._retain(storage, account, digest, body)

        webhooks = WebhookEventRepository(self.session, account.tenant_id)
        webhook_event_id = await webhooks.add_ignore(
            provider_account_id=account.id,
            provider_event_id=provider_event_id[:255],
            event_type=event_type,
            occurred_at=first.occurred_at if first else None,
            payload_digest=digest,
            payload_object_key=object_key,
        )
        if webhook_event_id is None:
            # Already accepted: a replay must not enqueue a second processing job.
            await self.session.commit()
            return WebhookAcceptance(
                webhook_event_id=None,
                duplicate=True,
                provider_event_id=provider_event_id,
                event_type=event_type,
            )

        await OutboxRepository(self.session).add(
            tenant_id=account.tenant_id,
            event_type=WEBHOOK_OUTBOX_EVENT,
            aggregate_type="webhook_event",
            aggregate_id=webhook_event_id,
            payload={
                "tenant_id": str(account.tenant_id),
                "webhook_event_id": str(webhook_event_id),
            },
            dedupe_key=f"{WEBHOOK_OUTBOX_EVENT}:{webhook_event_id}",
        )
        await self.session.commit()
        return WebhookAcceptance(
            webhook_event_id=webhook_event_id,
            duplicate=False,
            provider_event_id=provider_event_id,
            event_type=event_type,
        )

    # ---------------------------------------------------------------- helpers
    def _adapter(self, account: ProviderAccount) -> ProviderAdapter:
        try:
            return get_adapter(account.provider, settings=self.settings)
        except Exception as exc:  # noqa: BLE001 - surfaced as an actionable 422
            raise ValidationAppError(
                "No adapter is registered for this provider",
                extra={"reason": "unknown_provider", "provider": account.provider},
            ) from exc

    def _webhook_secret(self, account: ProviderAccount) -> Secret:
        if not account.webhook_secret_ciphertext or account.webhook_secret_key_version is None:
            raise ForbiddenError("Webhooks are not configured for this account")
        try:
            box = get_secret_box_provider().box_for(account.webhook_secret_key_version)
            value = box.decrypt(account.webhook_secret_ciphertext)
        except EncryptionKeyError as exc:
            raise ForbiddenError("Webhook credentials are unavailable") from exc
        return Secret(value, label=f"webhook:{account.provider}")

    def _normalize(self, adapter: ProviderAdapter, body: bytes) -> list[NormalizedProviderEvent]:
        """Best-effort read of the event identity for the dedup key.

        Failure here never blocks acceptance: the raw body is retained and the
        worker re-normalizes it, but a payload we cannot parse still has a
        content digest, so the replay defence holds either way.
        """
        try:
            return list(adapter.normalize_webhook(body))
        except Exception:  # noqa: BLE001 - malformed payload is handled downstream
            return []

    async def _retain(
        self,
        storage: ObjectStorage,
        account: ProviderAccount,
        digest: str,
        body: bytes,
    ) -> str:
        key = f"webhooks/{account.tenant_id}/{account.id}/{digest}.json"
        try:
            await asyncio.to_thread(storage.put_bytes, key, body)
        except Exception as exc:  # noqa: BLE001 - fail closed, let the provider retry
            raise ServiceUnavailableError(
                "Webhook payload could not be retained; retry later",
                extra={"reason": "payload_retention_failed"},
            ) from exc
        return key
