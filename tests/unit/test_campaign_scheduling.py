"""UTC scheduling with explicit DST ambiguous/nonexistent-time handling."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.campaign.scheduling import (
    AMBIGUOUS_LATEST,
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_NONEXISTENT,
    RESOLUTION_UNAMBIGUOUS,
    normalize_utc,
    resolve_schedule,
)
from app.errors import ValidationAppError


def test_unambiguous_time_round_trips_to_utc() -> None:
    resolved = resolve_schedule(datetime(2026, 6, 1, 9, 0), "Asia/Shanghai")
    assert resolved.resolution == RESOLUTION_UNAMBIGUOUS
    assert not resolved.adjusted
    assert resolved.timezone == "Asia/Shanghai"
    # Asia/Shanghai is UTC+8 year round.
    assert resolved.scheduled_at == datetime(2026, 6, 1, 1, 0, tzinfo=UTC)


def test_ambiguous_fall_back_uses_earliest_by_default() -> None:
    # 2024-11-03 01:30 occurs twice in New York (EDT -04:00 then EST -05:00).
    resolved = resolve_schedule(datetime(2024, 11, 3, 1, 30), "America/New_York")
    assert resolved.resolution == RESOLUTION_AMBIGUOUS
    assert resolved.adjusted
    assert resolved.scheduled_at == datetime(2024, 11, 3, 5, 30, tzinfo=UTC)


def test_ambiguous_fall_back_honours_latest_policy() -> None:
    resolved = resolve_schedule(
        datetime(2024, 11, 3, 1, 30), "America/New_York", on_ambiguous=AMBIGUOUS_LATEST
    )
    assert resolved.resolution == RESOLUTION_AMBIGUOUS
    assert resolved.scheduled_at == datetime(2024, 11, 3, 6, 30, tzinfo=UTC)


def test_nonexistent_spring_forward_time_is_reported() -> None:
    # 2024-03-10 02:30 does not exist in New York (clocks jump 02:00 -> 03:00).
    resolved = resolve_schedule(datetime(2024, 3, 10, 2, 30), "America/New_York")
    assert resolved.resolution == RESOLUTION_NONEXISTENT
    assert resolved.adjusted
    assert resolved.scheduled_at == datetime(2024, 3, 10, 7, 30, tzinfo=UTC)


def test_aware_local_time_is_converted_before_resolution() -> None:
    aware = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    resolved = resolve_schedule(aware, "Asia/Shanghai")
    # 09:00 UTC is 17:00 in Shanghai; the local wall clock is what is resolved.
    assert resolved.local_time == datetime(2026, 6, 1, 17, 0)
    assert resolved.scheduled_at == aware


def test_unknown_timezone_rejected() -> None:
    with pytest.raises(ValidationAppError) as excinfo:
        resolve_schedule(datetime(2026, 1, 1, 0, 0), "Mars/Olympus")
    assert excinfo.value.extra["reason"] == "invalid_timezone"


def test_unknown_ambiguous_policy_rejected() -> None:
    with pytest.raises(ValidationAppError) as excinfo:
        resolve_schedule(
            datetime(2024, 11, 3, 1, 30), "America/New_York", on_ambiguous="middle"
        )
    assert excinfo.value.extra["reason"] == "invalid_ambiguous_policy"


def test_normalize_utc_assumes_naive_is_utc() -> None:
    assert normalize_utc(datetime(2026, 1, 1, 0, 0)) == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert normalize_utc(datetime(2026, 1, 1, 8, 0, tzinfo=UTC)) == datetime(
        2026, 1, 1, 8, 0, tzinfo=UTC
    )
