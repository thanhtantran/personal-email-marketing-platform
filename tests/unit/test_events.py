"""Recipient event vocabulary, dedup keys and the monotonic reducer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.events.reducer import (
    derived_event_key,
    provider_event_key,
    reduce_recipient_status,
)
from app.domain.events.vocabulary import (
    EVENT_BOUNCED_HARD,
    EVENT_COMPLAINED,
    EVENT_DELIVERED,
    EVENT_OPENED,
    EVENT_REJECTED,
    EVENT_SUBMITTED,
    EVENT_UNKNOWN,
    EVENT_UNSUBSCRIBED,
    NORMALIZED_EVENT_TYPES,
    SUPPRESSION_REASON_BY_EVENT,
)

ACCOUNT = uuid.uuid4()


# --------------------------------------------------------------------- reducer
def test_acceptance_marks_unresolved_recipient_accepted() -> None:
    assert reduce_recipient_status(None, event_type=EVENT_DELIVERED) == "accepted"
    assert reduce_recipient_status("queued", event_type=EVENT_SUBMITTED) == "accepted"
    assert reduce_recipient_status("unknown", event_type=EVENT_DELIVERED) == "accepted"


def test_failure_is_definitive_and_not_overridden_by_late_acceptance() -> None:
    assert reduce_recipient_status("accepted", event_type=EVENT_BOUNCED_HARD) == "failed"
    assert reduce_recipient_status("accepted", event_type=EVENT_REJECTED) == "failed"
    # Out-of-order: a delivery report that arrives after the bounce cannot undo it.
    assert reduce_recipient_status("failed", event_type=EVENT_DELIVERED) is None


def test_repeated_acceptance_is_a_no_op() -> None:
    assert reduce_recipient_status("accepted", event_type=EVENT_DELIVERED) is None


def test_unknown_only_marks_unresolved_recipients() -> None:
    assert reduce_recipient_status("queued", event_type=EVENT_UNKNOWN) == "unknown"
    assert reduce_recipient_status("accepted", event_type=EVENT_UNKNOWN) is None
    assert reduce_recipient_status("failed", event_type=EVENT_UNKNOWN) is None
    assert reduce_recipient_status("unknown", event_type=EVENT_UNKNOWN) is None


def test_skipped_recipient_is_never_revived() -> None:
    assert reduce_recipient_status("skipped", event_type=EVENT_DELIVERED) is None


def test_informational_events_never_move_the_ledger() -> None:
    for event_type in (EVENT_OPENED, EVENT_COMPLAINED, EVENT_UNSUBSCRIBED):
        assert reduce_recipient_status("accepted", event_type=event_type) is None


# ------------------------------------------------------------------ event keys
def test_provider_event_key_is_scoped_to_the_account() -> None:
    key = provider_event_key(
        provider_account_id=ACCOUNT, provider_event_id="evt_1", event_type=EVENT_DELIVERED
    )
    assert key == f"provider:{ACCOUNT}:evt_1:delivered"
    other = provider_event_key(
        provider_account_id=uuid.uuid4(),
        provider_event_id="evt_1",
        event_type=EVENT_DELIVERED,
    )
    assert other != key


def test_provider_event_key_is_bounded() -> None:
    key = provider_event_key(
        provider_account_id=ACCOUNT, provider_event_id="x" * 500, event_type=EVENT_DELIVERED
    )
    assert len(key) <= 128


def test_derived_event_key_is_deterministic_and_hides_the_email() -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    key = derived_event_key(
        source="unsubscribe",
        event_type=EVENT_UNSUBSCRIBED,
        occurred_at=moment,
        recipient_email="person@example.com",
    )
    assert "@" not in key and "example.com" not in key
    assert key == derived_event_key(
        source="unsubscribe",
        event_type=EVENT_UNSUBSCRIBED,
        occurred_at=moment,
        recipient_email="person@example.com",
    )
    assert key != derived_event_key(
        source="unsubscribe",
        event_type=EVENT_OPENED,
        occurred_at=moment,
        recipient_email="person@example.com",
    )


# ------------------------------------------------------------------ vocabulary
def test_normalized_vocabulary_is_stable() -> None:
    assert EVENT_DELIVERED in NORMALIZED_EVENT_TYPES
    assert "received" not in NORMALIZED_EVENT_TYPES


def test_suppression_reasons_cover_authoritative_signals() -> None:
    assert SUPPRESSION_REASON_BY_EVENT[EVENT_COMPLAINED] == "complaint"
    assert SUPPRESSION_REASON_BY_EVENT[EVENT_BOUNCED_HARD] == "hard_bounce"
    assert SUPPRESSION_REASON_BY_EVENT[EVENT_UNSUBSCRIBED] == "unsubscribe"
    # A delivered/opened message is never a suppression signal.
    assert EVENT_DELIVERED not in SUPPRESSION_REASON_BY_EVENT
