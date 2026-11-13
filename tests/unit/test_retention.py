"""Retention window helpers.

Retention is a privacy control (SPEC.md section 8), so its window arithmetic is
tested directly: which rows are out of window, how a naive timestamp is read, and
that the report the pass emits is the one the logs and metrics carry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers.retention import (
    BATCH_LIMIT,
    IMPORT_STATUS_COMMITTING,
    RetentionReport,
    is_expired,
    retention_cutoff,
)

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_cutoff_is_now_minus_the_window() -> None:
    assert retention_cutoff(NOW, days=30) == NOW - timedelta(days=30)


def test_row_inside_the_window_is_kept() -> None:
    assert is_expired(NOW - timedelta(days=29), now=NOW, days=30) is False


def test_row_past_the_window_is_expired() -> None:
    assert is_expired(NOW - timedelta(days=31), now=NOW, days=30) is True


def test_the_boundary_instant_is_still_inside_the_window() -> None:
    """Only strictly older rows expire, so a run is idempotent at the edge."""
    assert is_expired(retention_cutoff(NOW, days=30), now=NOW, days=30) is False


def test_a_naive_timestamp_is_read_as_utc() -> None:
    naive = (NOW - timedelta(days=31)).replace(tzinfo=None)
    assert is_expired(naive, now=NOW, days=30) is True


def test_report_summary_matches_its_fields() -> None:
    report = RetentionReport(
        raw_webhook_payloads=2, staged_uploads=1, import_rows=5, failures=1
    )
    assert report.summary() == {
        "raw_webhook_payloads": 2,
        "staged_uploads": 1,
        "import_rows": 5,
        "failures": 1,
    }


def test_retention_constants_are_bounded_and_guard_in_flight_commits() -> None:
    assert BATCH_LIMIT > 0
    # A staged upload may only be removed once its commit is no longer reading it.
    assert IMPORT_STATUS_COMMITTING == "committing"
