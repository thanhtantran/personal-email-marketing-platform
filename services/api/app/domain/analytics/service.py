"""Campaign analytics derived from the recipient ledger and the event stream.

Two sources are read on purpose, because they answer different questions
(SPEC.md sections 7 and 10):

* the recipient ledger is the *current* state of each send -- how many are still
  queued, accepted, failed or unresolved;
* ``message_events`` is the provider's *reported* history -- how many distinct
  recipients were reported delivered, bounced, complained or unsubscribed.

Provider acceptance and provider-reported delivery are therefore never conflated:
``accepted`` comes from the ledger, ``delivered`` counts distinct delivered
events, and a message the provider has not yet reported on stays ``unknown``
rather than being inferred. Reads are non-destructive and every number is
reproducible from stored rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.campaign import (
    RECIPIENT_STATUS_ACCEPTED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_QUEUED,
    RECIPIENT_STATUS_RETRY,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNKNOWN,
)
from app.domain.events.vocabulary import (
    EVENT_BOUNCED_HARD,
    EVENT_BOUNCED_SOFT,
    EVENT_CLICKED,
    EVENT_COMPLAINED,
    EVENT_DEFERRED,
    EVENT_DELIVERED,
    EVENT_OPENED,
    EVENT_UNSUBSCRIBED,
)
from app.repositories.campaign_repo import CampaignRecipientRepository
from app.repositories.event_repo import MessageEventRepository

CAVEAT_ASYNC = (
    "Provider webhooks arrive asynchronously; reported counts can lag behind the "
    "provider's own state."
)
CAVEAT_ACCEPTANCE = (
    "accepted is a provider acceptance; delivered is a provider-reported delivery. "
    "accepted is always greater than or equal to delivered."
)
CAVEAT_UNKNOWN = (
    "unknown recipients have an ambiguous provider outcome; they are never retried "
    "automatically and are resolved by a later authoritative event."
)
CAVEAT_TRACKING_OFF = (
    "Open and click tracking is disabled and unsubscribes can only be counted from "
    "provider reports, so opened/clicked are zero by design."
)


@dataclass(frozen=True)
class CampaignAnalytics:
    campaign_id: uuid.UUID
    #: Ledger totals.
    total_recipients: int
    queued: int
    accepted: int
    failed: int
    skipped: int
    unknown: int
    #: Provider-reported totals, as distinct recipients.
    delivered: int
    deferred: int
    bounced: int
    bounced_hard: int
    bounced_soft: int
    complained: int
    unsubscribed: int
    opened: int
    clicked: int
    #: Why these numbers should be read with care.
    caveats: tuple[str, ...] = field(default_factory=tuple)


class CampaignAnalyticsService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, settings: Settings
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.recipients = CampaignRecipientRepository(session, tenant_id)
        self.events = MessageEventRepository(session, tenant_id)

    async def for_campaign(self, campaign_id: uuid.UUID) -> CampaignAnalytics:
        ledger = await self.recipients.counts_by_status(campaign_id)
        delivered = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_DELIVERED
        )
        bounced_hard = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_BOUNCED_HARD
        )
        bounced_soft = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_BOUNCED_SOFT
        )
        bounced = await self.events.count_distinct_recipients_for_types(
            campaign_id, event_types=(EVENT_BOUNCED_HARD, EVENT_BOUNCED_SOFT)
        )
        deferred = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_DEFERRED
        )
        complained = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_COMPLAINED
        )
        unsubscribed = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_UNSUBSCRIBED
        )
        opened = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_OPENED
        )
        clicked = await self.events.count_distinct_recipients(
            campaign_id, event_type=EVENT_CLICKED
        )

        return CampaignAnalytics(
            campaign_id=campaign_id,
            total_recipients=sum(ledger.values()),
            queued=ledger.get(RECIPIENT_STATUS_QUEUED, 0)
            + ledger.get(RECIPIENT_STATUS_RETRY, 0),
            accepted=ledger.get(RECIPIENT_STATUS_ACCEPTED, 0),
            failed=ledger.get(RECIPIENT_STATUS_FAILED, 0),
            skipped=ledger.get(RECIPIENT_STATUS_SKIPPED, 0),
            unknown=ledger.get(RECIPIENT_STATUS_UNKNOWN, 0),
            delivered=delivered,
            deferred=deferred,
            bounced=bounced,
            bounced_hard=bounced_hard,
            bounced_soft=bounced_soft,
            complained=complained,
            unsubscribed=unsubscribed,
            opened=opened,
            clicked=clicked,
            caveats=self._caveats(),
        )

    def _caveats(self) -> tuple[str, ...]:
        caveats = [CAVEAT_ASYNC, CAVEAT_ACCEPTANCE, CAVEAT_UNKNOWN]
        if not self.settings.tracking_enabled:
            caveats.append(CAVEAT_TRACKING_OFF)
        return tuple(caveats)
