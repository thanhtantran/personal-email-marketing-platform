"""Recipient event reducer and event-key derivation.

The reducer is deliberately monotonic (SPEC.md section 7): events arrive in any
order and may be delivered twice, so it never regresses a confirmed outcome, it
lets a later authoritative event resolve ``unknown``, and it never lets a weak
signal (open, click, complaint) rewrite a successful delivery.

``event_key`` is the dedup key for ``message_events``. When the provider supplies
an event id it is used directly, because a redelivery of the same event must
collapse onto one row. When it is absent the key is a digest over the provider
account plus the canonical event fields; that trades an astronomically small
collision risk for the ability to dedupe a provider that sends no ids
(SPEC.md section 7).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.db.models.campaign import (
    RECIPIENT_STATUS_ACCEPTED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNKNOWN,
)
from app.domain.events.vocabulary import (
    ACCEPTANCE_EVENTS,
    EVENT_UNKNOWN,
    FAILURE_EVENTS,
)

#: Ledger states that already record a final outcome. A weak or overlapping
#: event must not move the recipient out of one of these.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {RECIPIENT_STATUS_ACCEPTED, RECIPIENT_STATUS_FAILED, RECIPIENT_STATUS_SKIPPED}
)


def reduce_recipient_status(current: str | None, *, event_type: str) -> str | None:
    """Return the ledger status a new event implies, or ``None`` for no change.

    Rules, in priority order:

    * a failure is definitive: it sets ``failed`` and a later acceptance event
      cannot undo it (a bounce is the provider's own verdict);
    * an acceptance event sets ``accepted`` unless the ledger already records a
      confirmed failure or skip;
    * ``unknown`` only marks a recipient that is otherwise unresolved, and any
      later authoritative event resolves it;
    * every other event is informational and leaves the ledger untouched.
    """
    if event_type in FAILURE_EVENTS:
        return None if current == RECIPIENT_STATUS_FAILED else RECIPIENT_STATUS_FAILED
    if event_type in ACCEPTANCE_EVENTS:
        if current in {RECIPIENT_STATUS_FAILED, RECIPIENT_STATUS_SKIPPED}:
            return None
        return None if current == RECIPIENT_STATUS_ACCEPTED else RECIPIENT_STATUS_ACCEPTED
    if event_type == EVENT_UNKNOWN:
        if current in TERMINAL_STATUSES:
            return None
        return None if current == RECIPIENT_STATUS_UNKNOWN else RECIPIENT_STATUS_UNKNOWN
    return None


def provider_event_key(
    *, provider_account_id: object, provider_event_id: str, event_type: str
) -> str:
    """Dedup key for an event the provider identified.

    The provider event id is scoped to the account, so both are part of the key;
    two accounts may legitimately reuse the same id.
    """
    key = f"provider:{provider_account_id}:{provider_event_id}:{event_type}"
    return key[:128]


def derived_event_key(
    *,
    source: str,
    event_type: str,
    occurred_at: datetime | None,
    provider_account_id: object | None = None,
    provider_message_id: str | None = None,
    recipient_email: str | None = None,
) -> str:
    """Stable digest key for an event that carries no provider id.

    Email is folded into the digest rather than stored in the key so the key can
    be logged without disclosing the address (SPEC.md section 8).
    """
    canonical = {
        "source": source,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "provider_account_id": str(provider_account_id) if provider_account_id else None,
        "provider_message_id": provider_message_id,
        "recipient_email_digest": _digest(recipient_email) if recipient_email else None,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return f"{source}:{_digest(payload)}"[:128]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
