"""Consent and suppression policy.

These helpers encode a safety invariant: a contact is eligible for marketing
only when it is active, explicitly consented, not soft-deleted, and not
suppressed. Suppression is authoritative and outranks contact fields or campaign
snapshots (SPEC.md invariants 5 and 8).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, and_, select

from app.db.models import Contact, Suppression

CONTACT_STATUSES: tuple[str, ...] = ("active", "unsubscribed", "suppressed", "invalid")
CONSENT_STATUSES: tuple[str, ...] = ("granted", "denied", "unknown", "pending")
SUPPRESSION_REASONS: tuple[str, ...] = (
    "unsubscribe",
    "complaint",
    "hard_bounce",
    "manual",
    "import",
)

ELIGIBLE_CONTACT_STATUS = "active"
ELIGIBLE_CONSENT_STATUS = "granted"

# Suppression reasons that mirror into an unrecoverable contact status.
_STATUS_BY_REASON: dict[str, str] = {
    "unsubscribe": "unsubscribed",
    "complaint": "suppressed",
    "hard_bounce": "suppressed",
}


def is_eligible(*, status: str, consent_status: str) -> bool:
    """Whether a contact passes the status/consent gate used before any send."""
    return status == ELIGIBLE_CONTACT_STATUS and consent_status == ELIGIBLE_CONSENT_STATUS


def status_for_suppression_reason(reason: str) -> str | None:
    return _STATUS_BY_REASON.get(reason)


def suppressed_statuses() -> set[str]:
    return set(_STATUS_BY_REASON.values())


def eligible_contact_filter(tenant_id: uuid.UUID) -> ColumnElement[bool]:
    """SQL predicate matching contacts eligible for a marketing send.

    Excludes inactive/invalid contacts, non-consented contacts, soft-deleted
    contacts, and any contact with a live (non-expired) suppression record.
    """
    suppression = (
        select(Suppression.id)
        .where(
            Suppression.tenant_id == tenant_id,
            Suppression.normalized_email == Contact.normalized_email,
        )
        .exists()
    )
    return and_(
        Contact.tenant_id == tenant_id,
        Contact.deleted_at.is_(None),
        Contact.status == ELIGIBLE_CONTACT_STATUS,
        Contact.consent_status == ELIGIBLE_CONSENT_STATUS,
        ~suppression,
    )
