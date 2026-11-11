"""Import endpoints: staged upload, preview and idempotent commit.

The client requests an import, PUTs the CSV to a short-lived presigned URL, then
previews and commits. Commit is replay-safe: a completed import returns its
stored result instead of applying rows a second time.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.audience.import_service import UPLOAD_URL_TTL_SECONDS, ImportService
from app.repositories.audit_repo import AuditRepository
from app.schemas.audience import (
    ImportCommitRequest,
    ImportCreate,
    ImportCreated,
    ImportOut,
    ImportPreview,
    ImportPreviewRow,
)
from app.storage.base import ObjectStorage
from app.storage.s3 import get_storage

router = APIRouter(tags=["imports"])

PREVIEW_ERROR_LIMIT = 200


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _service(db: AsyncSession, context: TenantContext, storage: ObjectStorage,
             settings: Settings) -> ImportService:
    return ImportService(db, context.tenant.id, storage, settings)


@router.post("/imports", response_model=ImportCreated, status_code=201)
async def create_import(
    payload: ImportCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ImportCreated:
    service = _service(db, context, storage, settings)
    job, upload_url = await service.create(
        mapping=payload.mapping,
        created_by=context.user.id,
        idempotency_key=idempotency_key,
    )
    await AuditRepository(db, context.tenant.id).record(
        action="import.created",
        actor_user_id=context.user.id,
        object_type="import",
        object_id=str(job.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return ImportCreated(
        import_id=job.id,
        status=job.status,
        upload_url=upload_url,
        upload_expires_seconds=UPLOAD_URL_TTL_SECONDS,
    )


@router.get("/imports/{import_id}", response_model=ImportOut)
async def get_import(
    import_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ImportOut:
    job = await _service(db, context, storage, settings).get(import_id)
    return ImportOut.model_validate(job)


@router.post("/imports/{import_id}/preview", response_model=ImportPreview)
async def preview_import(
    import_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ImportPreview:
    job, plan = await _service(db, context, storage, settings).preview(import_id)
    errors = [row for row in plan.rows if row.error_code]
    return ImportPreview(
        import_id=job.id,
        status=job.status,
        counts=plan.counts,
        truncated=plan.truncated,
        errors=[
            ImportPreviewRow(
                row_number=row.row_number, outcome=row.outcome, error_code=row.error_code
            )
            for row in errors[:PREVIEW_ERROR_LIMIT]
        ],
        errors_truncated=len(errors) > PREVIEW_ERROR_LIMIT,
    )


@router.post("/imports/{import_id}/commit", response_model=ImportOut)
async def commit_import(
    import_id: uuid.UUID,
    payload: ImportCommitRequest,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> ImportOut:
    job, plan = await _service(db, context, storage, settings).commit(
        import_id, merge_policy=payload.merge_policy
    )
    await AuditRepository(db, context.tenant.id).record(
        action="import.committed",
        actor_user_id=context.user.id,
        object_type="import",
        object_id=str(job.id),
        request_id=_request_id(request),
        details={"merge_policy": payload.merge_policy, "replayed": plan is None},
    )
    await db.commit()
    return ImportOut.model_validate(job)
