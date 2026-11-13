"""Campaign endpoints: draft management, validation, scheduling and lifecycle.

Every state change runs through ``CampaignService`` so the API, scheduler and
workers share one lifecycle state machine. Launch freezes content plus the
recipient ledger and enqueues dispatch in a single transaction; create/launch
honour an ``Idempotency-Key`` header so a retried request cannot duplicate a
campaign or its recipients (IMPLEMENTATION_PLAN Stage 4).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.config import Settings, get_settings
from app.db.models import Campaign
from app.db.session import get_db
from app.domain.analytics import CampaignAnalyticsService
from app.domain.campaign.lifecycle import CAMPAIGN_STATUSES
from app.domain.campaign.scheduling import AMBIGUOUS_POLICIES, RESOLUTION_UNAMBIGUOUS
from app.domain.campaign.service import CampaignService
from app.domain.pagination import decode_cursor, encode_cursor
from app.errors import ValidationAppError
from app.repositories.audit_repo import AuditRepository
from app.schemas.campaign import (
    CampaignCreate,
    CampaignOut,
    CampaignPage,
    CampaignSummary,
    CampaignUpdate,
    LaunchIssueOut,
    LaunchResult,
    LaunchValidationResult,
    RecipientOut,
    RecipientPage,
    ScheduleRequest,
    ScheduleResult,
)
from app.schemas.event import CampaignAnalyticsOut

router = APIRouter(tags=["campaigns"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key")
) -> str | None:
    return value


def _validate_status(status: str, allowed: tuple[str, ...]) -> None:
    if status not in allowed:
        raise ValidationAppError(
            "Unsupported campaign status",
            extra={"reason": "invalid_status", "allowed": list(allowed)},
        )


@router.get("/campaigns", response_model=CampaignPage)
async def list_campaigns(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignPage:
    if status is not None:
        _validate_status(status, CAMPAIGN_STATUSES)
    service = CampaignService(db, context.tenant.id, get_settings())
    rows = await service.campaigns.list_page(
        limit=limit, cursor=decode_cursor(cursor), status=status
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return CampaignPage(
        items=[CampaignSummary.model_validate(campaign) for campaign in items],
        next_cursor=next_cursor,
        total=await service.campaigns.count(status=status),
    )


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    payload: CampaignCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Depends(_idempotency_key),
) -> CampaignOut:
    service = CampaignService(db, context.tenant.id, settings)
    campaign = await service.create(
        fields=payload.model_dump(),
        created_by=context.user.id,
        idempotency_key=idempotency_key,
    )
    await AuditRepository(db, context.tenant.id).record(
        action="campaign.created",
        actor_user_id=context.user.id,
        object_type="campaign",
        object_id=str(campaign.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return CampaignOut.model_validate(campaign)


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    service = CampaignService(db, context.tenant.id, get_settings())
    campaign = await service.get(campaign_id)
    return CampaignOut.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignOut:
    fields = payload.model_dump(exclude_unset=True)
    service = CampaignService(db, context.tenant.id, settings)
    campaign = await service.update(campaign_id, fields=fields)
    await AuditRepository(db, context.tenant.id).record(
        action="campaign.updated",
        actor_user_id=context.user.id,
        object_type="campaign",
        object_id=str(campaign.id),
        request_id=_request_id(request),
        details={"fields": sorted(fields)},
    )
    await db.commit()
    return CampaignOut.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/validate", response_model=LaunchValidationResult)
async def validate_campaign(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LaunchValidationResult:
    """Dry-run the launch gate; nothing is persisted, frozen or enqueued."""
    service = CampaignService(db, context.tenant.id, settings)
    check = await service.check_launch(campaign_id)
    return LaunchValidationResult(
        campaign_id=campaign_id,
        ok=check.ok,
        issues=[LaunchIssueOut(code=issue.code, detail=issue.detail) for issue in check.issues],
    )


@router.post("/campaigns/{campaign_id}/schedule", response_model=ScheduleResult)
async def schedule_campaign(
    campaign_id: uuid.UUID,
    payload: ScheduleRequest,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScheduleResult:
    if payload.on_ambiguous not in AMBIGUOUS_POLICIES:
        raise ValidationAppError(
            "Unsupported ambiguous-time policy",
            extra={"reason": "invalid_ambiguous_policy", "allowed": list(AMBIGUOUS_POLICIES)},
        )
    service = CampaignService(db, context.tenant.id, settings)
    campaign, resolved = await service.schedule(
        campaign_id,
        scheduled_at=payload.scheduled_at,
        timezone=payload.timezone,
        on_ambiguous=payload.on_ambiguous,
    )
    await AuditRepository(db, context.tenant.id).record(
        action="campaign.scheduled",
        actor_user_id=context.user.id,
        object_type="campaign",
        object_id=str(campaign.id),
        request_id=_request_id(request),
        details={
            "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
            "timezone": campaign.scheduled_timezone,
            "resolution": resolved.resolution if resolved else RESOLUTION_UNAMBIGUOUS,
        },
    )
    await db.commit()
    assert campaign.scheduled_at is not None
    return ScheduleResult(
        campaign=CampaignOut.model_validate(campaign),
        scheduled_at=campaign.scheduled_at,
        timezone=campaign.scheduled_timezone or settings.default_timezone,
        resolution=resolved.resolution if resolved else RESOLUTION_UNAMBIGUOUS,
    )


@router.post("/campaigns/{campaign_id}/launch", response_model=LaunchResult)
async def launch_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Depends(_idempotency_key),
) -> LaunchResult:
    service = CampaignService(db, context.tenant.id, settings)
    campaign, count = await service.launch(campaign_id, idempotency_key=idempotency_key)
    if count is None:
        count = await service.recipients.count_for_campaign(campaign_id)
    snapshot = await service.snapshots.latest(campaign_id)
    await AuditRepository(db, context.tenant.id).record(
        action="campaign.launched",
        actor_user_id=context.user.id,
        object_type="campaign",
        object_id=str(campaign.id),
        request_id=_request_id(request),
        details={
            "recipient_count": count,
            "snapshot_version": snapshot.snapshot_version if snapshot else None,
        },
    )
    await db.commit()
    return LaunchResult(
        campaign_id=campaign.id,
        status=campaign.status,
        recipient_count=count,
        snapshot_version=snapshot.snapshot_version if snapshot else None,
    )


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignOut)
async def pause_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignOut:
    service = CampaignService(db, context.tenant.id, settings)
    campaign = await service.pause(campaign_id)
    await _record_transition(db, context, request, campaign, "campaign.paused")
    await db.commit()
    return CampaignOut.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignOut)
async def resume_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignOut:
    service = CampaignService(db, context.tenant.id, settings)
    campaign = await service.resume(campaign_id)
    await _record_transition(db, context, request, campaign, "campaign.resumed")
    await db.commit()
    return CampaignOut.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignOut:
    service = CampaignService(db, context.tenant.id, settings)
    campaign = await service.cancel(campaign_id)
    await _record_transition(db, context, request, campaign, "campaign.cancelled")
    await db.commit()
    return CampaignOut.model_validate(campaign)


@router.get("/campaigns/{campaign_id}/recipients", response_model=RecipientPage)
async def list_recipients(
    campaign_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecipientPage:
    """Paged view of the frozen recipient ledger for a launched campaign."""
    service = CampaignService(db, context.tenant.id, settings)
    await service.get(campaign_id)
    rows = await service.recipients.list_page(
        campaign_id, limit=limit, cursor=decode_cursor(cursor), status=status
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return RecipientPage(
        items=[RecipientOut.model_validate(recipient) for recipient in items],
        next_cursor=next_cursor,
        total=await service.recipients.count_for_campaign(campaign_id, status=status),
    )


@router.get("/campaigns/{campaign_id}/analytics", response_model=CampaignAnalyticsOut)
async def campaign_analytics(
    campaign_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CampaignAnalyticsOut:
    """Ledger state plus provider-reported delivery, with reading caveats.

    ``accepted`` is a provider acceptance and ``delivered`` is a provider-reported
    delivery; the two are never conflated and an unresolved recipient stays
    ``unknown`` rather than being assumed delivered (SPEC.md sections 7 and 10).
    """
    service = CampaignService(db, context.tenant.id, settings)
    await service.get(campaign_id)
    summary = await CampaignAnalyticsService(db, context.tenant.id, settings).for_campaign(
        campaign_id
    )
    return CampaignAnalyticsOut.model_validate(summary)


async def _record_transition(
    db: AsyncSession,
    context: TenantContext,
    request: Request,
    campaign: Campaign,
    action: str,
) -> None:
    await AuditRepository(db, context.tenant.id).record(
        action=action,
        actor_user_id=context.user.id,
        object_type="campaign",
        object_id=str(campaign.id),
        request_id=_request_id(request),
        details={"status": campaign.status},
    )
