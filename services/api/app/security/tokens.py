"""Security primitives: opaque tokens and constant-time comparison."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_token(nbytes: int = 32) -> str:
    """Return a URL-safe random token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash a token for storage. Tokens are high-entropy, so SHA-256 suffices."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
