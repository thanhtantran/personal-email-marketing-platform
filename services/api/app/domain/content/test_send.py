"""Controlled test sends.

Until the provider gateway exists (Stage 5/6) a deterministic mock sender is used:
it renders the personalization and returns the exact message that would be sent,
without contacting a provider and without creating any campaign or recipient rows
(IMPLEMENTATION_PLAN Stage 3 exit gate).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.errors import ForbiddenError

MOCK_PROVIDER = "mock"


@dataclass(frozen=True)
class TestMessage:
    to: str
    subject: str
    html: str
    text: str
    digest: str
    provider: str
    enqueued: bool


def is_verified_recipient(email: str, allowed: set[str]) -> bool:
    return email.strip().lower() in allowed


def require_verified_recipient(email: str, allowed: set[str]) -> str:
    """Normalize the recipient or reject it as not verified for test sends."""
    normalized = email.strip().lower()
    if not is_verified_recipient(normalized, allowed):
        raise ForbiddenError(
            "Test sends are restricted to verified addresses",
            extra={"reason": "unverified_test_recipient"},
        )
    return normalized


def build_test_message(*, recipient: str, subject: str, html: str, text: str) -> TestMessage:
    digest = hashlib.sha256(
        "\n".join([recipient, subject, html, text]).encode("utf-8")
    ).hexdigest()
    return TestMessage(
        to=recipient,
        subject=subject,
        html=html,
        text=text,
        digest=digest,
        provider=MOCK_PROVIDER,
        enqueued=False,
    )


class MockSender:
    """Deterministic stand-in for the provider gateway; never touches the network."""

    name = MOCK_PROVIDER
    enqueues_production = False

    def send(self, message: TestMessage) -> TestMessage:
        return message
