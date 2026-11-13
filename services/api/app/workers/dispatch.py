"""Campaign dispatch loop.

The outbox publishes exactly one ``campaign.dispatch`` event when a campaign is
launched; this module turns that single event into the per-recipient submission
loop of SPEC.md section 5. One pass:

1. reconciles recipients left ``unknown`` by an earlier ambiguous attempt,
   because an ambiguous request must never be resubmitted until reconciliation
   has proven it was not accepted (SPEC.md invariant 6),
2. claims one due recipient at a time under ``FOR UPDATE SKIP LOCKED`` and submits
   it through the provider gateway, committing that recipient's attempt and
   ledger outcome before claiming the next one, so a retry is never duplicated,
3. stops immediately when the gateway reports routing is held (global marketing
   pause, or no account may legally carry the message), leaving untouched work
   for a later pass,
4. re-enqueues a deferred ``campaign.dispatch`` event at the earliest retry time
   when classified retries remain, and marks the campaign ``completed`` once the
   ledger holds neither a dispatchable row nor an unresolved ``unknown``.

Nothing here invents capacity, eligibility or delivery state; it only drives the
gateway and records what the gateway decided (SPEC.md invariants 4, 6 and 9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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
from app.domain.campaign.lifecycle import allows_dispatch, ensure_transition
from app.domain.gateway import ProviderGateway, SubmissionReport
from app.logging import get_logger
from app.repositories.campaign_repo import (
    CampaignRecipientRepository,
    CampaignRepository,
    CampaignSnapshotRepository,
)
from app.repositories.outbox_repo import OutboxRepository

logger = get_logger(__name__)

OUTBOX_EVENT_DISPATCH = "campaign.dispatch"


@dataclass
class DispatchPass:
    """What one dispatch pass did, for the worker log and the task result."""

    campaign_id: uuid.UUID
    submitted: int = 0
    accepted: int = 0
    retried: int = 0
    unknown: int = 0
    skipped: int = 0
    failed: int = 0
    reconciled: int = 0
    #: Dispatchable recipients still owed a submission when the pass ended.
    remaining: int = 0
    #: Recipients still ``unknown`` and awaiting reconciliation.
    unresolved: int = 0
    held: bool = False
    hold_reason: str | None = None
    completed: bool = False

    def summary(self) -> str:
        if self.completed:
            return "completed"
        if self.held:
            return "held"
        if self.remaining or self.unresolved:
            return "sending"
        return "idle"


def _tally(report: DispatchPass, result: SubmissionReport) -> None:
    report.submitted += 1
    if result.status == RECIPIENT_STATUS_ACCEPTED:
        report.accepted += 1
    elif result.status == RECIPIENT_STATUS_RETRY:
        report.retried += 1
    elif result.status == RECIPIENT_STATUS_UNKNOWN:
        report.unknown += 1
    elif result.status == RECIPIENT_STATUS_SKIPPED:
        report.skipped += 1
    elif result.status == RECIPIENT_STATUS_FAILED:
        report.failed += 1


async def reconcile_campaign(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    settings: Settings,
    campaign_id: uuid.UUID,
    *,
    redis: object | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    """Resolve ambiguous recipients so a retry can only follow proven non-acceptance.

    Returns the number of recipients whose outcome became known; the rest stay
    ``unknown`` and remain visible to the operator.
    """
    recipients = CampaignRecipientRepository(session, tenant_id)
    gateway = ProviderGateway(session, tenant_id, settings, redis=redis, now=now)
    unresolved = await recipients.list_page(
        campaign_id, limit=limit, status=RECIPIENT_STATUS_UNKNOWN
    )
    resolved = 0
    for recipient in unresolved:
        report = await gateway.reconcile_recipient(recipient)
        if not report.needs_reconcile:
            resolved += 1
    return resolved


async def _remaining(
    recipients: CampaignRecipientRepository, campaign_id: uuid.UUID
) -> tuple[int, int, datetime | None]:
    """``(dispatchable, unresolved_unknown, earliest_retry_at)`` for the campaign."""
    queued = await recipients.count_for_campaign(campaign_id, status=RECIPIENT_STATUS_QUEUED)
    retry = await recipients.count_for_campaign(campaign_id, status=RECIPIENT_STATUS_RETRY)
    unknown = await recipients.count_for_campaign(campaign_id, status=RECIPIENT_STATUS_UNKNOWN)
    earliest = await recipients.earliest_due(campaign_id)
    return queued + retry, unknown, earliest


async def _schedule_next_pass(
    outbox: OutboxRepository,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    snapshot_version: int | None,
    available_at: datetime,
) -> None:
    """Enqueue the next dispatch pass, deduped per campaign/version/retry time."""
    bucket = int(available_at.timestamp())
    await outbox.add(
        tenant_id=tenant_id,
        event_type=OUTBOX_EVENT_DISPATCH,
        aggregate_type="campaign",
        aggregate_id=campaign_id,
        payload={
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id),
            "snapshot_version": snapshot_version,
        },
        dedupe_key=f"{OUTBOX_EVENT_DISPATCH}:{campaign_id}:{snapshot_version}:retry:{bucket}",
        available_at=available_at,
    )


async def dispatch_campaign(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    settings: Settings,
    campaign_id: uuid.UUID,
    *,
    snapshot_version: int | None = None,
    redis: object | None = None,
    max_recipients: int | None = None,
    now: datetime | None = None,
) -> DispatchPass:
    """Run one dispatch pass for a campaign already advanced to ``sending``."""
    moment = now or datetime.now(UTC)
    campaigns = CampaignRepository(session, tenant_id)
    recipients = CampaignRecipientRepository(session, tenant_id)
    snapshots = CampaignSnapshotRepository(session, tenant_id)
    outbox = OutboxRepository(session)

    report = DispatchPass(campaign_id=campaign_id)
    campaign = await campaigns.get(campaign_id)
    if campaign is None:
        report.hold_reason = "campaign_missing"
        return report

    snapshot = await snapshots.latest(campaign_id)
    content = dict(snapshot.content) if snapshot is not None else {}
    version = snapshot.snapshot_version if snapshot is not None else snapshot_version

    # Resolve ambiguous attempts before any retry is considered (invariant 6).
    report.reconciled = await reconcile_campaign(
        session, tenant_id, settings, campaign_id, redis=redis, now=now
    )
    await session.commit()

    gateway = ProviderGateway(session, tenant_id, settings, redis=redis, now=now)

    while True:
        current = await campaigns.get(campaign_id)
        if current is None:
            report.hold_reason = "campaign_missing"
            break
        if not allows_dispatch(current.status):
            # Pause/cancel/terminal: stop this pass without touching the ledger.
            report.held = True
            report.hold_reason = current.status
            break
        if max_recipients is not None and report.submitted >= max_recipients:
            break

        claimed = await recipients.claim_due(campaign_id, limit=1, now=gateway.now)
        if not claimed:
            break

        result = await gateway.submit_recipient(claimed[0], content)
        if result.held:
            # Nothing was written for this recipient; the pass stops held.
            report.held = True
            report.hold_reason = result.error_code
            break
        _tally(report, result)
        await session.commit()

    dispatchable, unresolved, earliest = await _remaining(recipients, campaign_id)
    report.remaining = dispatchable
    report.unresolved = unresolved

    if not report.held and dispatchable:
        # A future retry is still owed; wake the campaign up when it is due.
        await _schedule_next_pass(
            outbox,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            snapshot_version=version,
            available_at=earliest or moment,
        )

    if not report.held and dispatchable == 0 and unresolved == 0:
        locked = await campaigns.get_for_update(campaign_id)
        if locked is not None and locked.status == "sending":
            ensure_transition(locked.status, "completed")
            locked.status = "completed"
            report.completed = True

    await session.commit()
    logger.info(
        "campaign dispatch pass",
        extra={
            "campaign_id": str(campaign_id),
            "submitted": report.submitted,
            "accepted": report.accepted,
            "retried": report.retried,
            "unknown": report.unknown,
            "remaining": report.remaining,
            "held": report.held,
        },
    )
    return report
