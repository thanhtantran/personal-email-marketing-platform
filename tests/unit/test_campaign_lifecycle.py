"""Campaign lifecycle state machine: one authority for every transition."""

from __future__ import annotations

import pytest

from app.domain.campaign.lifecycle import (
    CAMPAIGN_STATUSES,
    allows_dispatch,
    can_transition,
    ensure_transition,
    is_editable,
    is_terminal,
)
from app.errors import ConflictError


def test_declared_statuses_are_complete() -> None:
    assert set(CAMPAIGN_STATUSES) == {
        "draft",
        "scheduled",
        "preparing",
        "sending",
        "paused",
        "completed",
        "cancelled",
        "failed",
    }


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "scheduled"),
        ("draft", "preparing"),
        ("scheduled", "preparing"),
        ("scheduled", "draft"),
        ("preparing", "sending"),
        ("preparing", "paused"),
        ("sending", "paused"),
        ("sending", "completed"),
        ("paused", "sending"),
        ("paused", "cancelled"),
    ],
)
def test_legal_transitions(current: str, target: str) -> None:
    assert can_transition(current, target)
    ensure_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "sending"),
        ("draft", "completed"),
        ("completed", "sending"),
        ("cancelled", "draft"),
        ("failed", "scheduled"),
        ("sending", "draft"),
    ],
)
def test_illegal_transitions_raise_conflict(current: str, target: str) -> None:
    assert not can_transition(current, target)
    with pytest.raises(ConflictError) as excinfo:
        ensure_transition(current, target)
    assert excinfo.value.extra["reason"] == "invalid_transition"


def test_terminal_and_editable_classification() -> None:
    assert all(is_terminal(status) for status in ("completed", "cancelled", "failed"))
    assert not is_terminal("sending")
    assert is_editable("draft")
    assert is_editable("scheduled")
    assert not is_editable("preparing")


def test_only_sending_allows_dispatch() -> None:
    """Pause/cancel must stop new submissions but keep accepted messages."""
    assert allows_dispatch("sending")
    for status in CAMPAIGN_STATUSES:
        if status != "sending":
            assert not allows_dispatch(status)
