"""Signed one-click unsubscribe.

The link carries no email address: the token is an HMAC over a small reference
payload (workspace, recipient, contact and campaign ids), so a leaked URL
discloses nothing about the recipient and cannot be edited to target anyone else
(SPEC.md section 8).

Recording the unsubscribe is a single idempotent suppression upsert, so a
replayed link, a mail-scanner prefetch and a provider ``unsubscribed`` webhook
all converge on one suppression record. The next dispatch eligibility check
already honours it, which is why one-click works even for a recipient that is
mid-flight (SPEC.md invariants 5 and 8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event import SOURCE_UNSUBSCRIBE
from app.domain.audience.suppression import apply_suppression
from app.domain.events.reducer import derived_event_key
from app.domain.events.vocabulary import EVENT_UNSUBSCRIBED
from app.repositories.campaign_repo import CampaignRecipientRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.event_repo import MessageEventRepository
from app.security.signing import SignatureError, sign_payload, verify_payload

#: Marker in the token payload so a token minted for another purpose is rejected.
TOKEN_KIND = "unsubscribe"

#: Suppression reason recorded by the one-click path.
UNSUBSCRIBE_REASON = "unsubscribe"


@dataclass(frozen=True)
class UnsubscribeTarget:
    """The opaque references a verified token resolves to (never an email)."""

    tenant_id: uuid.UUID
    recipient_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    issued_at: int | None = None


@dataclass(frozen=True)
class UnsubscribeOutcome:
    suppression_recorded: bool
    normalized_email: str | None = None
    contact_mirrored: bool = False
    event_recorded: bool = False


def build_unsubscribe_token(
    secret: str,
    *,
    tenant_id: uuid.UUID,
    recipient_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    issued_at: float | None = None,
) -> str:
    """Return a signed, PII-free unsubscribe token for one recipient."""
    payload: dict[str, Any] = {
        "k": TOKEN_KIND,
        "t": str(tenant_id),
        "r": str(recipient_id) if recipient_id else None,
        "c": str(contact_id) if contact_id else None,
        "cid": str(campaign_id) if campaign_id else None,
    }
    return sign_payload(secret, payload, issued_at=issued_at)


def verify_unsubscribe_token(
    secret: str,
    token: str,
    *,
    ttl_seconds: int | None = None,
    now: float | None = None,
) -> UnsubscribeTarget:
    """Verify and decode an unsubscribe token, raising ``SignatureError``.

    A forged, malformed or wrong-purpose token is rejected before any state is
    touched, so an attacker cannot unsubscribe an address they do not hold.
    """
    payload = verify_payload(secret, token, ttl_seconds=ttl_seconds, now=now)
    if payload.get("k") != TOKEN_KIND:
        raise SignatureError("not an unsubscribe token")
    try:
        tenant_id = uuid.UUID(str(payload["t"]))
    except (KeyError, ValueError) as exc:
        raise SignatureError("malformed unsubscribe token") from exc
    return UnsubscribeTarget(
        tenant_id=tenant_id,
        recipient_id=_maybe_uuid(payload.get("r")),
        contact_id=_maybe_uuid(payload.get("c")),
        campaign_id=_maybe_uuid(payload.get("cid")),
        issued_at=int(payload["iat"]) if isinstance(payload.get("iat"), (int, float)) else None,
    )


async def record_unsubscribe(
    session: AsyncSession,
    target: UnsubscribeTarget,
    *,
    occurred_at: datetime | None = None,
) -> UnsubscribeOutcome:
    """Record the suppression an unsubscribe implies, idempotently.

    The recipient ledger is preferred because it carries the address the send
    was snapshotted with; the contact is the fallback. Either way the address is
    resolved server-side from the opaque reference, never from the URL.
    """
    email: str | None = None
    recipient = None
    if target.recipient_id is not None:
        recipient = await CampaignRecipientRepository(session, target.tenant_id).get(
            target.recipient_id
        )
        if recipient is not None:
            email = recipient.email_snapshot
    if email is None and target.contact_id is not None:
        contact = await ContactRepository(session, target.tenant_id).get(target.contact_id)
        if contact is not None:
            email = contact.normalized_email

    if email is None:
        return UnsubscribeOutcome(suppression_recorded=False)

    await apply_suppression(
        session,
        target.tenant_id,
        normalized_email=email,
        reason=UNSUBSCRIBE_REASON,
        source=SOURCE_UNSUBSCRIBE,
        occurred_at=occurred_at,
        evidence={
            "recipient_id": str(target.recipient_id) if target.recipient_id else None,
            "contact_id": str(target.contact_id) if target.contact_id else None,
        },
    )

    event_recorded = await _record_event(session, target, recipient, email, occurred_at)
    return UnsubscribeOutcome(
        suppression_recorded=True,
        normalized_email=email,
        event_recorded=event_recorded,
    )


async def _record_event(
    session: AsyncSession,
    target: UnsubscribeTarget,
    recipient,
    email: str,
    occurred_at: datetime | None,
) -> bool:
    """Timeline entry so first-party unsubscribes are visible in analytics."""
    if recipient is None or recipient.provider_account_id is None:
        return False
    moment = occurred_at or recipient.outcome_at or recipient.created_at
    key = derived_event_key(
        source=SOURCE_UNSUBSCRIBE,
        event_type=EVENT_UNSUBSCRIBED,
        occurred_at=moment,
        provider_account_id=recipient.provider_account_id,
        provider_message_id=recipient.provider_message_id,
        recipient_email=email,
    )
    return await MessageEventRepository(session, target.tenant_id).add_ignore(
        campaign_id=recipient.campaign_id,
        recipient_id=recipient.id,
        provider_account_id=recipient.provider_account_id,
        event_type=EVENT_UNSUBSCRIBED,
        event_key=key,
        occurred_at=moment,
        source=SOURCE_UNSUBSCRIBE,
        metadata={"recipient_id": str(recipient.id)},
    )


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def unsubscribe_url(base_url: str, token: str) -> str:
    """Absolute, PII-free unsubscribe URL embedded in the message."""
    return f"{base_url.rstrip('/')}/unsubscribe/{token}"


def unsubscribe_headers(
    *,
    base_url: str,
    secret: str,
    tenant_id: uuid.UUID,
    recipient_id: uuid.UUID,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """RFC 8058 one-click headers for a marketing message.

    ``List-Unsubscribe-Post`` lets a mailbox provider unsubscribe the recipient
    with a single POST to the same URL, without opening a page.
    """
    token = build_unsubscribe_token(
        secret,
        tenant_id=tenant_id,
        recipient_id=recipient_id,
        contact_id=contact_id,
        campaign_id=campaign_id,
    )
    url = unsubscribe_url(base_url, token)
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
