"""HMAC-signed opaque tokens.

Used for self-contained, tamper-evident references: staged upload handles and
signed unsubscribe links. The payload never contains an email address, so a
leaked token cannot disclose recipient PII (SPEC.md section 8).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any


class SignatureError(Exception):
    """Raised when a signed token is malformed, forged or expired."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_payload(secret: str, payload: dict[str, Any], *, issued_at: float | None = None) -> str:
    body = dict(payload)
    body.setdefault("iat", int(issued_at if issued_at is not None else time.time()))
    encoded = _b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    )
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_payload(
    secret: str,
    token: str,
    *,
    ttl_seconds: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    if not token or token.count(".") != 1:
        raise SignatureError("malformed token")
    encoded, signature = token.split(".")
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    try:
        provided = _b64decode(signature)
    except (ValueError, binascii.Error) as exc:
        raise SignatureError("malformed signature") from exc
    if not hmac.compare_digest(expected, provided):
        raise SignatureError("invalid signature")
    try:
        payload = json.loads(_b64decode(encoded))
    except ValueError as exc:
        raise SignatureError("malformed payload") from exc
    if not isinstance(payload, dict):
        raise SignatureError("malformed payload")
    if ttl_seconds is not None:
        issued = payload.get("iat")
        if not isinstance(issued, (int, float)):
            raise SignatureError("missing issued-at")
        if (now if now is not None else time.time()) - issued > ttl_seconds:
            raise SignatureError("expired token")
    return payload
