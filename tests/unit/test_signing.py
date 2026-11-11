"""HMAC-signed opaque tokens: integrity, forgery and expiry."""

from __future__ import annotations

import pytest

from app.security.signing import SignatureError, sign_payload, verify_payload


def test_round_trip_returns_payload() -> None:
    token = sign_payload("secret", {"kind": "unsubscribe", "ref": "abc"}, issued_at=1000)
    payload = verify_payload("secret", token, ttl_seconds=60, now=1030)
    assert payload["kind"] == "unsubscribe"
    assert payload["ref"] == "abc"
    assert payload["iat"] == 1000


def test_wrong_secret_is_rejected() -> None:
    token = sign_payload("secret", {"k": "v"})
    with pytest.raises(SignatureError):
        verify_payload("other-secret", token)


def test_tampered_payload_is_rejected() -> None:
    token = sign_payload("secret", {"k": "v"})
    _, signature = token.split(".")
    forged = sign_payload("secret", {"k": "tampered"})
    with pytest.raises(SignatureError):
        verify_payload("secret", f"{forged.split('.')[0]}.{signature}")


def test_expired_token_is_rejected() -> None:
    token = sign_payload("secret", {"k": "v"}, issued_at=1000)
    with pytest.raises(SignatureError):
        verify_payload("secret", token, ttl_seconds=10, now=2000)


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(SignatureError):
        verify_payload("secret", "not-a-token")
