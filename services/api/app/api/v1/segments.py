"""Segment endpoints.

Definitions are validated into an allowlisted AST before storage, so an operator
can never smuggle SQL through a segment. The estimate separates the raw match
count from the marketing-eligible count (suppressed/unsubscribed/non-consented
contacts excluded), which keeps an estimate from advertising recipients that
dispatch would reject.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.db.session import get_db
from app.domain.audience.segments import validate_definition
from app.errors import NotFoundError
from app.repositories.audit_repo import AuditRepository
from app.repositories.segment_repo import SegmentRepository
from app.schemas.audience import SegmentCreate, SegmentEstimate, SegmentOut, SegmentUpdate

router = APIRouter(tags=["segments"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/segments", response_model=list[SegmentOut])
async def list_segments(
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[SegmentOut]:
    segments = await SegmentRepository(db, context.tenant.id).list_all()
    return [SegmentOut.model_validate(segment) for segment in segments]


@router.post("/segments", response_model=SegmentOut, status_code=201)
async def create_segment(
    payload: SegmentCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    definition = validate_definition(payload.definition)
    repo = SegmentRepository(db, context.tenant.id)
    segment = await repo.create(name=payload.name.strip(), definition=definition)
    await AuditRepository(db, context.tenant.id).record(
        action="segment.created",
        actor_user_id=context.user.id,
        object_type="segment",
        object_id=str(segment.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return SegmentOut.model_validate(segment)


@router.get("/segments/{segment_id}", response_model=SegmentOut)
async def get_segment(
    segment_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    segment = await SegmentRepository(db, context.tenant.id).get(segment_id)
    if segment is None:
        raise NotFoundError("Segment not found")
    return SegmentOut.model_validate(segment)


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
async def update_segment(
    segment_id: uuid.UUID,
    payload: SegmentUpdate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    repo = SegmentRepository(db, context.tenant.id)
    segment = await repo.get(segment_id)
    if segment is None:
        raise NotFoundError("Segment not found")
    definition = validate_definition(payload.definition)
    segment = await repo.update(segment, name=payload.name.strip(), definition=definition)
    await AuditRepository(db, context.tenant.id).record(
        action="segment.updated",
        actor_user_id=context.user.id,
        object_type="segment",
        object_id=str(segment.id),
        request_id=_request_id(request),
        details={"version": segment.version},
    )
    await db.commit()
    return SegmentOut.model_validate(segment)


@router.get("/segments/{segment_id}/estimate", response_model=SegmentEstimate)
async def estimate_segment(
    segment_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> SegmentEstimate:
    repo = SegmentRepository(db, context.tenant.id)
    segment = await repo.get(segment_id)
    if segment is None:
        raise NotFoundError("Segment not found")
    return SegmentEstimate(
        segment_id=segment.id,
        match_count=await repo.match_count(segment.definition),
        eligible_count=await repo.eligible_count(segment.definition),
    )
