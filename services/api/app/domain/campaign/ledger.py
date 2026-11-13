"""Recipient ledger construction.

The ledger holds one row per resolved recipient. ``idempotency_key`` is a
deterministic digest of campaign + address and the table is unique on both
``(campaign_id, email_snapshot)`` and ``(tenant_id, idempotency_key)``, so a
replayed launch or a restarted worker can never insert the same recipient twice
(SPEC.md section 5; ARCHITECTURE.md section 7).
"""

from __future__ import annotations

import hashlib
import uuid

RECIPIENT_STATUS_QUEUED = "queued"
RECIPIENT_STATUS_ACCEPTED = "accepted"
RECIPIENT_STATUS_FAILED = "failed"
RECIPIENT_STATUS_SKIPPED = "skipped"
RECIPIENT_STATUS_UNKNOWN = "unknown"


def recipient_idempotency_key(campaign_id: uuid.UUID, normalized_email: str) -> str:
    """Deterministic, stable per-recipient key (64 hex chars)."""
    return hashlib.sha256(f"{campaign_id}:{normalized_email}".encode()).hexdigest()


def ledger_row(campaign_id: uuid.UUID, *, contact_id: uuid.UUID, normalized_email: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "contact_id": contact_id,
        "email_snapshot": normalized_email,
        "status": RECIPIENT_STATUS_QUEUED,
        "idempotency_key": recipient_idempotency_key(campaign_id, normalized_email),
    }
