"""Provider account endpoints: operator config, verification and routing control.

An account is the quota/rate/routing boundary and a credential is only a
write-only secret that reaches it, so no response here ever carries a secret
value (SPEC.md sections 4 and 6). Verification and capacity refresh ask the
provider through its adapter and persist the dated facts the router acts on;
the routing endpoints expose *why* marketing traffic can or cannot route.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.pagination import decode_cursor, encode_cursor
from app.domain.provider.service import ACCOUNT_STATUSES, ProviderAccountService
from app.errors import ValidationAppError
from app.schemas.provider import (
    CapacityOut,
    CapacityRefreshResult,
    CredentialCreate,
    CredentialOut,
    ProviderAccountCreate,
    ProviderAccountDetail,
    ProviderAccountOut,
    ProviderAccountPage,
    ProviderAccountUpdate,
    RoutingControlRequest,
    RoutingStatusOut,
    VerificationOut,
    VerifyResult,
)

router = APIRouter(tags=["provider-accounts"])


@router.get("/provider-accounts", response_model=ProviderAccountPage)
async def list_provider_accounts(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderAccountPage:
    if status is not None and status not in ACCOUNT_STATUSES:
        raise ValidationAppError(
            "Unsupported account status",
            extra={"reason": "invalid_status", "allowed": sorted(ACCOUNT_STATUSES)},
        )
    service = ProviderAccountService(db, context.tenant.id, settings)
    rows = await service.list_page(limit=limit, cursor=decode_cursor(cursor), status=status)
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return ProviderAccountPage(
        items=[ProviderAccountOut.model_validate(account) for account in items],
        next_cursor=next_cursor,
        total=await service.count(status=status),
    )


@router.post("/provider-accounts", response_model=ProviderAccountDetail, status_code=201)
async def create_provider_account(
    payload: ProviderAccountCreate,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderAccountDetail:
    """Register an account and its first credential (secret is write-only)."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    account = await service.create(
        provider=payload.provider,
        external_account_ref=payload.external_account_ref,
        display_name=payload.display_name,
        eligible_message_classes=payload.eligible_message_classes,
        sender_domains=payload.sender_domains,
        routing_priority=payload.routing_priority,
        routing_weight=payload.routing_weight,
        secret=payload.secret,
        secret_label=payload.secret_label,
    )
    _, credentials = await service.get_with_credentials(account.id)
    await db.commit()
    detail = ProviderAccountDetail.model_validate(account)
    detail.credentials = [CredentialOut.model_validate(item) for item in credentials]
    return detail


@router.get("/provider-accounts/routing-status", response_model=RoutingStatusOut)
async def get_routing_status(
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RoutingStatusOut:
    """Why marketing traffic can or cannot route right now, per account."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    status = await service.routing_status()
    return RoutingStatusOut(
        marketing_paused=status.paused,
        paused_reason=status.pause_reason,
        marketing_eligible=status.marketing_eligible,
        capacity_fresh=status.capacity_fresh,
        exclusions=status.exclusions,
    )


@router.post("/provider-accounts/routing-pause", response_model=RoutingStatusOut)
async def set_routing_pause(
    payload: RoutingControlRequest,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RoutingStatusOut:
    """Halt or resume marketing routing for the whole tenant."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    await service.set_paused(
        paused=payload.paused, reason=payload.reason, actor_user_id=context.user.id
    )
    status = await service.routing_status()
    await db.commit()
    return RoutingStatusOut(
        marketing_paused=status.paused,
        paused_reason=status.pause_reason,
        marketing_eligible=status.marketing_eligible,
        capacity_fresh=status.capacity_fresh,
        exclusions=status.exclusions,
    )


@router.get("/provider-accounts/{account_id}", response_model=ProviderAccountDetail)
async def get_provider_account(
    account_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderAccountDetail:
    service = ProviderAccountService(db, context.tenant.id, settings)
    account, credentials = await service.get_with_credentials(account_id)
    detail = ProviderAccountDetail.model_validate(account)
    detail.credentials = [CredentialOut.model_validate(item) for item in credentials]
    return detail


@router.patch("/provider-accounts/{account_id}", response_model=ProviderAccountOut)
async def update_provider_account(
    account_id: uuid.UUID,
    payload: ProviderAccountUpdate,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderAccountOut:
    service = ProviderAccountService(db, context.tenant.id, settings)
    account = await service.update(account_id, fields=payload.model_dump(exclude_unset=True))
    await db.commit()
    return ProviderAccountOut.model_validate(account)


@router.post(
    "/provider-accounts/{account_id}/credentials",
    response_model=CredentialOut,
    status_code=201,
)
async def add_credential(
    account_id: uuid.UUID,
    payload: CredentialCreate,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CredentialOut:
    """Attach a credential to an account; it never changes the account's quota."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    credential = await service.add_credential(
        account_id, secret=payload.secret, label=payload.label
    )
    await db.commit()
    return CredentialOut.model_validate(credential)


@router.post(
    "/provider-accounts/{account_id}/credentials/{credential_id}/revoke",
    response_model=CredentialOut,
)
async def revoke_credential(
    account_id: uuid.UUID,
    credential_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CredentialOut:
    service = ProviderAccountService(db, context.tenant.id, settings)
    credential = await service.revoke_credential(account_id, credential_id)
    await db.commit()
    return CredentialOut.model_validate(credential)


@router.post("/provider-accounts/{account_id}/verify", response_model=VerifyResult)
async def verify_provider_account(
    account_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VerifyResult:
    """Ask the provider to confirm the account and record the dated facts."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    account, verification = await service.verify(account_id)
    await db.commit()
    return VerifyResult(
        account=ProviderAccountOut.model_validate(account),
        verification=VerificationOut(
            valid=verification.valid,
            health_state=verification.health_state,
            eligible_message_classes=sorted(verification.eligible_message_classes),
            sender_domains=list(verification.sender_domains),
            observed_by=verification.observed_by,
            detail=verification.detail,
        ),
    )


@router.post(
    "/provider-accounts/{account_id}/refresh-quota", response_model=CapacityRefreshResult
)
async def refresh_provider_account_capacity(
    account_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CapacityRefreshResult:
    """Record the provider's freshest capacity facts; unknown stays unknown."""
    service = ProviderAccountService(db, context.tenant.id, settings)
    account, snapshot = await service.refresh_capacity(account_id)
    await db.commit()
    return CapacityRefreshResult(
        account=ProviderAccountOut.model_validate(account),
        capacity=CapacityOut(
            observed_at=snapshot.observed_at,
            source=snapshot.source,
            daily_limit=snapshot.daily_limit,
            daily_used=snapshot.daily_used,
            monthly_limit=snapshot.monthly_limit,
            monthly_used=snapshot.monthly_used,
            rate_per_second=snapshot.rate_per_second,
            notes=snapshot.notes,
        ),
    )
