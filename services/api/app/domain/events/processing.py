"""Asynchronous normalization and application of an accepted webhook delivery.

The worker re-reads the durable row under a row lock and re-normalizes the raw
payload it retained at intake. Because the work is idempotent end to end --
inserts use ``ON CONFLICT DO NOTHING`` and suppression is an idempotent upsert --
an outbox redelivery, a retried task or a duplicate provider event converges on
the same state (SPEC.md invariants 7 and 8).

Normalized events are stored individually and never overwritten: analytics can
then report distinct recipients and total events separately. The reducer only
moves the recipient ledger's *current* status, monotonically.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import CampaignRecipient, ProviderAccount
from app.db.models.event import (
    SOURCE_PROVIDER_WEBHOOK,
    WEBHOOK_STATUS_FAILED,
    WEBHOOK_STATUS_IGNORED,
    WEBHOOK_STATUS_PROCESSED,
)
from app.domain.audience.emails import normalize_email
from app.domain.audience.suppression import apply_suppression
from app.domain.events.reducer import (
    derived_event_key,
    provider_event_key,
    reduce_recipient_status,
)
from app.domain.events.vocabulary import (
    NORMALIZED_EVENT_TYPES,
    SUPPRESSION_REASON_BY_EVENT,
)
from app.observability.metrics import RECIPIENT_EVENTS
from app.providers.contract import NormalizedProviderEvent
from app.providers.registry import get_adapter
from app.repositories.campaign_repo import CampaignRecipientRepository
from app.repositories.event_repo import MessageEventRepository, WebhookEventRepository
from app.repositories.provider_repo import ProviderAccountRepository
from app.storage.base import ObjectStorage

#: Coarse error code recorded on the ledger when an event proves a failure.
_ERROR_CODE_BY_EVENT: dict[str, str] = {
    "bounced_hard": "hard_bounce",
    "rejected": "rejected",
}


@dataclass(frozen=True)
class ProcessingReport:
    webhook_event_id: uuid.UUID
    status: str
    #: Normalized events that were new and moved (or could have moved) state.
    applied: int = 0
    #: Normalized events already present, i.e. a replay we correctly ignored.
    duplicates: int = 0
    #: Suppression records touched (complaint, hard bounce, unsubscribe).
    suppressions: int = 0


class WebhookProcessingService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, settings: Settings) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.webhooks = WebhookEventRepository(session, tenant_id)
        self.messages = MessageEventRepository(session, tenant_id)
        self.recipients = CampaignRecipientRepository(session, tenant_id)

    async def process(
        self, webhook_event_id: uuid.UUID, *, storage: ObjectStorage
    ) -> ProcessingReport:
        event = await self.webhooks.get_for_update(webhook_event_id)
        if event is None:
            return ProcessingReport(webhook_event_id, "missing")
        if event.status == WEBHOOK_STATUS_PROCESSED:
            return ProcessingReport(webhook_event_id, "already_processed")
        if not event.payload_object_key:
            await self.webhooks.mark_processed(
                event, when=datetime.now(UTC), status=WEBHOOK_STATUS_FAILED
            )
            await self.session.commit()
            return ProcessingReport(webhook_event_id, "no_payload")

        body = await asyncio.to_thread(storage.get_bytes, event.payload_object_key)
        account = await ProviderAccountRepository(self.session, self.tenant_id).get(
            event.provider_account_id
        )
        if account is None:
            await self.webhooks.mark_processed(
                event, when=datetime.now(UTC), status=WEBHOOK_STATUS_FAILED
            )
            await self.session.commit()
            return ProcessingReport(webhook_event_id, "no_account")
        adapter = self._adapter(account)

        normalized = list(adapter.normalize_webhook(body))

        applied = duplicates = suppressions = 0
        for item in normalized:
            suppressions += await self._apply_suppression(item)
            recipient = await self._resolve_recipient(item, account)
            if recipient is None:
                continue
            inserted = await self._record_event(item, recipient, account)
            if not inserted:
                duplicates += 1
                continue
            applied += 1
            await self._reduce(recipient, item)

        status = WEBHOOK_STATUS_PROCESSED if normalized else WEBHOOK_STATUS_IGNORED
        await self.webhooks.mark_processed(event, when=datetime.now(UTC), status=status)
        await self.session.commit()
        return ProcessingReport(
            webhook_event_id=webhook_event_id,
            status=status,
            applied=applied,
            duplicates=duplicates,
            suppressions=suppressions,
        )

    # ---------------------------------------------------------------- helpers
    def _adapter(self, account: ProviderAccount):
        return get_adapter(account.provider, settings=self.settings)

    async def _apply_suppression(self, item: NormalizedProviderEvent) -> int:
        """Complaint, hard bounce and unsubscribe suppress regardless of state."""
        reason = SUPPRESSION_REASON_BY_EVENT.get(item.event_type)
        if reason is None or not item.recipient_email:
            return 0
        email = normalize_email(item.recipient_email)
        if email is None:
            return 0
        await apply_suppression(
            self.session,
            self.tenant_id,
            normalized_email=email,
            reason=reason,
            source=SOURCE_PROVIDER_WEBHOOK,
            occurred_at=item.occurred_at,
            evidence={
                "event_type": item.event_type,
                "provider_event_id": item.provider_event_id,
            },
        )
        return 1

    async def _resolve_recipient(
        self, item: NormalizedProviderEvent, account: ProviderAccount
    ) -> CampaignRecipient | None:
        if item.provider_message_id:
            recipient = await self.recipients.get_by_provider_message_id(
                item.provider_message_id, provider_account_id=account.id
            )
            if recipient is not None:
                return recipient
        if item.recipient_email:
            email = normalize_email(item.recipient_email)
            if email is not None:
                return await self.recipients.get_latest_by_email(email)
        return None

    async def _record_event(
        self,
        item: NormalizedProviderEvent,
        recipient: CampaignRecipient,
        account: ProviderAccount,
    ) -> bool:
        event_type = (
            item.event_type if item.event_type in NORMALIZED_EVENT_TYPES else "unknown"
        )
        if item.provider_event_id:
            key = provider_event_key(
                provider_account_id=account.id,
                provider_event_id=item.provider_event_id,
                event_type=event_type,
            )
        else:
            key = derived_event_key(
                source=SOURCE_PROVIDER_WEBHOOK,
                event_type=event_type,
                occurred_at=item.occurred_at,
                provider_account_id=account.id,
                provider_message_id=item.provider_message_id,
                recipient_email=item.recipient_email,
            )
        inserted = await self.messages.add_ignore(
            campaign_id=recipient.campaign_id,
            recipient_id=recipient.id,
            provider_account_id=account.id,
            event_type=event_type,
            event_key=key,
            occurred_at=item.occurred_at,
            source=SOURCE_PROVIDER_WEBHOOK,
            metadata={
                "provider_event_id": item.provider_event_id,
                "provider_message_id": item.provider_message_id,
            },
        )
        RECIPIENT_EVENTS.inc(event_type=event_type, result="inserted" if inserted else "duplicate")
        return inserted

    async def _reduce(self, recipient: CampaignRecipient, item: NormalizedProviderEvent) -> None:
        target = reduce_recipient_status(recipient.status, event_type=item.event_type)
        if target is None or target == recipient.status:
            return
        await self.recipients.apply_event_status(
            recipient,
            status=target,
            when=item.occurred_at,
            error_code=_ERROR_CODE_BY_EVENT.get(item.event_type),
        )
