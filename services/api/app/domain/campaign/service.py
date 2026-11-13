"""Campaign lifecycle orchestration.

Every state change runs through the lifecycle state machine under a row lock,
and launch freezes content plus the recipient ledger in the same transaction
that writes the outbox event. A replayed request or a re-run scheduler pass
therefore cannot duplicate recipients or enqueue duplicate work
(IMPLEMENTATION_PLAN Stage 4 exit gate).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Campaign
from app.domain.campaign import ledger, snapshot
from app.domain.campaign.lifecycle import (
    allows_dispatch,
    ensure_transition,
    is_editable,
    is_terminal,
)
from app.domain.campaign.scheduling import (
    AMBIGUOUS_EARLIEST,
    ResolvedSchedule,
    resolve_schedule,
)
from app.domain.campaign.validation import LaunchCheck, validate_launch
from app.errors import ConflictError, NotFoundError, ValidationAppError
from app.repositories.campaign_repo import (
    CampaignRecipientRepository,
    CampaignRepository,
    CampaignSnapshotRepository,
)
from app.repositories.contact_repo import ContactRepository
from app.repositories.idempotency_repo import IdempotencyRepository
from app.repositories.outbox_repo import OutboxRepository
from app.repositories.segment_repo import SegmentRepository
from app.repositories.template_repo import TemplateRepository

OUTBOX_EVENT_DISPATCH = "campaign.dispatch"
SCOPE_CAMPAIGN_CREATE = "campaign.create"
SCOPE_CAMPAIGN_LAUNCH = "campaign.launch"

# Field names an operator may change while a campaign is still editable.
EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "subject",
        "from_name",
        "from_email",
        "reply_to",
        "template_id",
        "segment_id",
    }
)


def _request_hash(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class CampaignService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, settings: Settings) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.campaigns = CampaignRepository(session, tenant_id)
        self.snapshots = CampaignSnapshotRepository(session, tenant_id)
        self.recipients = CampaignRecipientRepository(session, tenant_id)
        self.contacts = ContactRepository(session, tenant_id)
        self.segments = SegmentRepository(session, tenant_id)
        self.templates = TemplateRepository(session, tenant_id)
        self.idempotency = IdempotencyRepository(session, tenant_id)
        self.outbox = OutboxRepository(session)

    # ---------------------------------------------------------------- drafts
    async def get(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.campaigns.get(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found")
        return campaign

    async def create(
        self,
        *,
        fields: dict,
        created_by: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Campaign:
        request_hash = _request_hash(fields)
        record = None
        if idempotency_key:
            record, created = await self.idempotency.reserve(
                scope=SCOPE_CAMPAIGN_CREATE, key=idempotency_key, request_hash=request_hash
            )
            if not created:
                if record.request_hash != request_hash:
                    raise ConflictError(
                        "Idempotency key already used with a different request",
                        extra={"reason": "idempotency_conflict"},
                    )
                if record.object_id is not None:
                    existing = await self.campaigns.get(record.object_id)
                    if existing is not None:
                        return existing
        await self._validate_references(
            template_id=fields.get("template_id"), segment_id=fields.get("segment_id")
        )
        campaign = await self.campaigns.create(created_by=created_by, **fields)
        if record is not None:
            await self.idempotency.attach_object(record, campaign.id)
        return campaign

    async def update(self, campaign_id: uuid.UUID, *, fields: dict) -> Campaign:
        campaign = await self._locked(campaign_id)
        if not is_editable(campaign.status):
            raise ConflictError(
                "Campaign content can only be edited before launch",
                extra={"reason": "campaign_not_editable", "status": campaign.status},
            )
        updates = {key: value for key, value in fields.items() if key in EDITABLE_FIELDS}
        await self._validate_references(
            template_id=updates.get("template_id"), segment_id=updates.get("segment_id")
        )
        if updates:
            await self.campaigns.update_fields(campaign, updates)
        return campaign

    # ------------------------------------------------------------- scheduling
    async def schedule(
        self,
        campaign_id: uuid.UUID,
        *,
        scheduled_at: datetime | None,
        timezone: str | None = None,
        on_ambiguous: str = AMBIGUOUS_EARLIEST,
    ) -> tuple[Campaign, ResolvedSchedule | None]:
        campaign = await self._locked(campaign_id)
        ensure_transition(campaign.status, "scheduled")
        tz = timezone or self.settings.default_timezone
        resolved: ResolvedSchedule | None = None
        if scheduled_at is None:
            campaign.scheduled_at = datetime.now(UTC)
            campaign.scheduled_timezone = tz
        else:
            resolved = resolve_schedule(scheduled_at, tz, on_ambiguous=on_ambiguous)
            if resolved.scheduled_at <= datetime.now(UTC):
                raise ValidationAppError(
                    "Scheduled time must be in the future",
                    extra={"reason": "schedule_in_past"},
                )
            campaign.scheduled_at = resolved.scheduled_at
            campaign.scheduled_timezone = resolved.timezone
        campaign.status = "scheduled"
        await self.session.flush()
        return campaign, resolved

    # ------------------------------------------------------------- validation
    async def check_launch(self, campaign_id: uuid.UUID) -> LaunchCheck:
        campaign = await self.get(campaign_id)
        return await self._check(campaign)

    async def _check(self, campaign: Campaign) -> LaunchCheck:
        template = (
            await self.templates.get(campaign.template_id, include_archived=True)
            if campaign.template_id
            else None
        )
        segment = await self.segments.get(campaign.segment_id) if campaign.segment_id else None
        eligible = (
            await self.segments.eligible_count(segment.definition) if segment is not None else 0
        )
        provider_eligible, capacity_fresh = self._provider_readiness()
        return validate_launch(
            campaign,
            template=template,
            segment=segment,
            eligible_recipients=eligible,
            provider_eligible=provider_eligible,
            capacity_fresh=capacity_fresh,
        )

    def _provider_readiness(self) -> tuple[bool, bool]:
        """Return ``(provider_eligible, capacity_fresh)`` for the launch gate.

        Provider accounts, their marketing eligibility and capacity snapshots
        are modelled in Stage 5. Until account rows exist there is nothing to
        consult, so launch proceeds on the local-only path; Stage 5 replaces
        this with a gateway query.
        """
        return True, True

    # ----------------------------------------------------------------- launch
    async def launch(
        self, campaign_id: uuid.UUID, *, idempotency_key: str | None = None
    ) -> tuple[Campaign, int | None]:
        campaign = await self._locked(campaign_id)
        request_hash = _request_hash({"campaign_id": str(campaign_id)})
        record = None
        if idempotency_key:
            record, created = await self.idempotency.reserve(
                scope=SCOPE_CAMPAIGN_LAUNCH, key=idempotency_key, request_hash=request_hash
            )
            if not created:
                if record.request_hash != request_hash:
                    raise ConflictError(
                        "Idempotency key already used with a different request",
                        extra={"reason": "idempotency_conflict"},
                    )
                if record.object_id is not None:
                    return campaign, None
        if campaign.status in {"preparing", "sending", "paused", "completed"}:
            # A retry after a successful freeze must not re-run it.
            return campaign, None

        check = await self._check(campaign)
        if not check.ok:
            raise ValidationAppError(
                "Campaign failed launch validation",
                extra={"reason": "launch_validation_failed", **check.as_extra()},
            )
        recipient_count = await self._freeze_and_enqueue(campaign)
        if record is not None:
            await self.idempotency.attach_object(record, campaign.id)
        return campaign, recipient_count

    async def _freeze_and_enqueue(self, campaign: Campaign) -> int:
        """Freeze content and recipients, then enqueue dispatch in one transaction."""
        ensure_transition(campaign.status, "preparing")
        template = (
            await self.templates.get(campaign.template_id, include_archived=True)
            if campaign.template_id
            else None
        )
        segment = await self.segments.get(campaign.segment_id) if campaign.segment_id else None
        definition = dict(segment.definition) if segment is not None else {}
        version = await self.snapshots.next_version(campaign.id)
        await self._build_ledger(campaign.id, definition)
        recipient_count = await self.recipients.count_for_campaign(campaign.id)

        await self.snapshots.create(
            campaign_id=campaign.id,
            content=snapshot.build_content_snapshot(campaign, template),
            audience_definition=snapshot.build_audience_snapshot(segment),
            recipient_count=recipient_count,
            snapshot_version=version,
        )
        campaign.status = "preparing"
        campaign.launched_at = datetime.now(UTC)
        if template is not None:
            campaign.template_version = template.version
        await self.outbox.add(
            tenant_id=self.tenant_id,
            event_type=OUTBOX_EVENT_DISPATCH,
            aggregate_type="campaign",
            aggregate_id=campaign.id,
            payload={
                "tenant_id": str(self.tenant_id),
                "campaign_id": str(campaign.id),
                "snapshot_version": version,
            },
            dedupe_key=f"{OUTBOX_EVENT_DISPATCH}:{campaign.id}:{version}",
        )
        await self.session.flush()
        return recipient_count

    async def _build_ledger(self, campaign_id: uuid.UUID, definition: dict) -> int:
        """Materialize recipients in bounded batches; insert is conflict-safe."""
        batch = self.settings.campaign_batch_size
        after: tuple[str, uuid.UUID] | None = None
        while True:
            contacts = await self.contacts.list_eligible(definition, limit=batch, after=after)
            if not contacts:
                break
            rows = [
                ledger.ledger_row(
                    campaign_id, contact_id=contact.id, normalized_email=contact.normalized_email
                )
                for contact in contacts
            ]
            await self.recipients.bulk_insert_ignore(rows)
            last = contacts[-1]
            after = (last.normalized_email, last.id)
            if len(contacts) < batch:
                break
        return await self.recipients.count_for_campaign(campaign_id)

    # ------------------------------------------------------- pause/resume/cancel
    async def pause(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._locked(campaign_id)
        ensure_transition(campaign.status, "paused")
        campaign.status = "paused"
        await self.session.flush()
        return campaign

    async def resume(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._locked(campaign_id)
        ensure_transition(campaign.status, "sending")
        campaign.status = "sending"
        await self.session.flush()
        return campaign

    async def cancel(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._locked(campaign_id)
        if campaign.status == "cancelled":
            return campaign
        if is_terminal(campaign.status):
            raise ConflictError(
                "Campaign has already finished",
                extra={"reason": "campaign_already_finished", "status": campaign.status},
            )
        ensure_transition(campaign.status, "cancelled")
        campaign.status = "cancelled"
        await self.session.flush()
        return campaign

    async def can_dispatch(self, campaign_id: uuid.UUID) -> bool:
        """Whether new recipient submissions are currently permitted."""
        campaign = await self.campaigns.get(campaign_id)
        if campaign is None:
            return False
        return allows_dispatch(campaign.status)

    # ---------------------------------------------------------------- helpers
    async def _locked(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.campaigns.get_for_update(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found")
        return campaign

    async def _validate_references(
        self, *, template_id: uuid.UUID | None, segment_id: uuid.UUID | None
    ) -> None:
        if template_id is not None:
            template = await self.templates.get(template_id, include_archived=True)
            if template is None:
                raise ValidationAppError(
                    "Referenced template was not found",
                    extra={"reason": "template_not_found"},
                )
        if segment_id is not None:
            segment = await self.segments.get(segment_id)
            if segment is None:
                raise ValidationAppError(
                    "Referenced segment was not found",
                    extra={"reason": "segment_not_found"},
                )
