"""Idempotent suppression application.

Recording a suppression and mirroring the unrecoverable contact status happen
in one place so the manual endpoint, the webhook processor and the one-click
unsubscribe path cannot disagree about what a suppression does. The underlying
upsert is idempotent: a duplicate webhook, a replayed unsubscribe link or a
retried worker converges on the existing row and never resets its original
occurrence time (SPEC.md invariants 5 and 8).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Suppression
from app.domain.audience.consent import status_for_suppression_reason
from app.repositories.contact_repo import ContactRepository
from app.repositories.suppression_repo import SuppressionRepository


async def apply_suppression(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    normalized_email: str,
    reason: str,
    source: str | None = None,
    occurred_at: datetime | None = None,
    evidence: dict | None = None,
) -> Suppression:
    """Record a suppression and mirror the contact status it implies."""
    record = await SuppressionRepository(session, tenant_id).upsert(
        normalized_email=normalized_email,
        reason=reason,
        source=source,
        occurred_at=occurred_at,
        evidence=evidence,
    )
    mirrored = status_for_suppression_reason(reason)
    if mirrored:
        contacts = ContactRepository(session, tenant_id)
        contact = await contacts.get_by_email(normalized_email)
        if contact is not None and contact.status != mirrored:
            await contacts.apply_fields(contact, {"status": mirrored})
    return record
