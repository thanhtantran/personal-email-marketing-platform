"""Cursor pagination helpers.

Cursor pagination keeps large audience listings stable while contacts are being
imported (SPEC.md section 4). The cursor encodes the last row's ``created_at``
and id, which form a total order.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime

from app.errors import ValidationAppError


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    payload = {"t": created_at.isoformat(), "i": str(row_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> tuple[datetime, uuid.UUID] | None:
    if not token:
        return None
    try:
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token + padding))
        created_at = datetime.fromisoformat(payload["t"])
        row_id = uuid.UUID(payload["i"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ValidationAppError(
            "Invalid pagination cursor", extra={"reason": "invalid_cursor"}
        ) from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at, row_id
