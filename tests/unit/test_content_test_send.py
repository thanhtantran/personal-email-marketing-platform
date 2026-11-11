"""Test sends are restricted and must never enqueue production mail."""

from __future__ import annotations

import pytest

from app.domain.content.test_send import (
    MockSender,
    build_test_message,
    is_verified_recipient,
    require_verified_recipient,
)
from app.errors import ForbiddenError

ALLOWED = {"owner@example.com", "qa@example.com"}


def test_verified_recipient_is_normalized() -> None:
    assert require_verified_recipient("  Owner@Example.com ", ALLOWED) == "owner@example.com"


def test_unverified_recipient_is_rejected() -> None:
    with pytest.raises(ForbiddenError) as excinfo:
        require_verified_recipient("stranger@example.com", ALLOWED)
    assert excinfo.value.extra.get("reason") == "unverified_test_recipient"


def test_is_verified_recipient_is_case_insensitive() -> None:
    assert is_verified_recipient("QA@example.com", ALLOWED) is True
    assert is_verified_recipient("nobody@example.com", ALLOWED) is False


def test_build_test_message_is_deterministic_and_not_enqueued() -> None:
    first = build_test_message(recipient="a@example.com", subject="Hi", html="<p>x</p>", text="x")
    second = build_test_message(recipient="a@example.com", subject="Hi", html="<p>x</p>", text="x")
    assert first.digest == second.digest
    assert first.enqueued is False
    assert first.provider == "mock"


def test_mock_sender_never_touches_production() -> None:
    sender = MockSender()
    assert sender.enqueues_production is False
    message = build_test_message(recipient="a@example.com", subject="Hi", html="<p>x</p>", text="x")
    assert sender.send(message) is message
