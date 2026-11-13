"""Signed one-click unsubscribe: token integrity, PII-free links, endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.domain.events.unsubscribe import (
    build_unsubscribe_token,
    unsubscribe_headers,
    unsubscribe_url,
    verify_unsubscribe_token,
)
from app.main import app
from app.security.signing import SignatureError, sign_payload

SECRET = "test-secret"
TENANT = uuid.uuid4()


def test_token_round_trip_exposes_only_opaque_ids() -> None:
    recipient_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    campaign_id = uuid.uuid4()
    token = build_unsubscribe_token(
        SECRET,
        tenant_id=TENANT,
        recipient_id=recipient_id,
        contact_id=contact_id,
        campaign_id=campaign_id,
        issued_at=1000,
    )
    target = verify_unsubscribe_token(SECRET, token)
    assert target.tenant_id == TENANT
    assert target.recipient_id == recipient_id
    assert target.contact_id == contact_id
    assert target.campaign_id == campaign_id
    assert target.issued_at == 1000


def test_token_never_contains_an_email_address() -> None:
    token = build_unsubscribe_token(SECRET, tenant_id=TENANT, recipient_id=uuid.uuid4())
    assert "@" not in token


def test_forged_token_is_rejected() -> None:
    token = build_unsubscribe_token(SECRET, tenant_id=TENANT, recipient_id=uuid.uuid4())
    with pytest.raises(SignatureError):
        verify_unsubscribe_token("other-secret", token)


def test_token_of_another_kind_is_rejected() -> None:
    foreign = sign_payload(SECRET, {"k": "upload", "t": str(TENANT)})
    with pytest.raises(SignatureError):
        verify_unsubscribe_token(SECRET, foreign)


def test_expired_token_is_rejected() -> None:
    token = build_unsubscribe_token(SECRET, tenant_id=TENANT, issued_at=1000)
    with pytest.raises(SignatureError):
        verify_unsubscribe_token(SECRET, token, ttl_seconds=10, now=2000)


def test_one_click_headers_advertise_a_post_target() -> None:
    token_recipient = uuid.uuid4()
    headers = unsubscribe_headers(
        base_url="https://mail.example.com/",
        secret=SECRET,
        tenant_id=TENANT,
        recipient_id=token_recipient,
        campaign_id=uuid.uuid4(),
    )
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert headers["List-Unsubscribe"].startswith("<https://mail.example.com/unsubscribe/")
    assert headers["List-Unsubscribe"].endswith(">")


def test_unsubscribe_url_does_not_double_the_slash() -> None:
    assert unsubscribe_url("https://a.test/", "tok") == "https://a.test/unsubscribe/tok"


def test_get_with_invalid_token_is_a_problem_response() -> None:
    response = TestClient(app).get("/unsubscribe/not-a-real-token")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["reason"] == "invalid_unsubscribe_token"


def test_get_with_valid_token_shows_confirmation_without_unsubscribing() -> None:
    settings = get_settings()
    token = build_unsubscribe_token(
        settings.session_key, tenant_id=TENANT, recipient_id=uuid.uuid4()
    )
    response = TestClient(app).get(f"/unsubscribe/{token}")
    # A confirmation page, not a state change: scanners issue GET requests.
    assert response.status_code == 200
    assert "unsubscribe" in response.text.lower()
