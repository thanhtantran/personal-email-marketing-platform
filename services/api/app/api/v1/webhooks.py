"""Provider webhook intake endpoint.

This route is public and unauthenticated: the provider cannot hold a session, so
authenticity comes from the signature over the raw body, checked *before* any
durable write. The raw body is read verbatim (never a parsed model) so the
signature the provider computed is the one we verify (SPEC.md section 8).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.events.intake import WebhookIntakeService
from app.schemas.event import WebhookAccepted
from app.storage.base import ObjectStorage
from app.storage.s3 import get_storage

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/{provider}/{account_public_id}",
    response_model=WebhookAccepted,
    status_code=202,
)
async def receive_webhook(
    provider: str,
    account_public_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> WebhookAccepted:
    body = await request.body()
    result = await WebhookIntakeService(db, settings).accept(
        provider=provider,
        account_public_id=account_public_id,
        headers=dict(request.headers),
        body=body,
        storage=storage,
    )
    return WebhookAccepted(
        accepted=not result.duplicate,
        duplicate=result.duplicate,
        event_type=result.event_type,
        provider_event_id=result.provider_event_id,
    )
