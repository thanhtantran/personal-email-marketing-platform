"""Outbox dispatcher helpers and idempotency-key hashing."""

from __future__ import annotations

from app.domain.campaign.service import _request_hash
from app.repositories.outbox_repo import STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED
from app.workers.outbox import EVENT_TASKS, MAX_BACKOFF_SECONDS, _backoff_seconds, task_for


def test_dispatch_event_maps_to_celery_task() -> None:
    assert task_for("campaign.dispatch") == "app.workers.tasks.dispatch_campaign"
    assert EVENT_TASKS["campaign.dispatch"].endswith("dispatch_campaign")


def test_unmapped_event_type_has_no_task() -> None:
    assert task_for("something.else") is None


def test_backoff_grows_exponentially_and_is_capped() -> None:
    assert _backoff_seconds(0) == 1
    assert _backoff_seconds(1) == 2
    assert _backoff_seconds(3) == 8
    assert _backoff_seconds(50) == MAX_BACKOFF_SECONDS


def test_outbox_status_constants_are_distinct() -> None:
    assert len({STATUS_PENDING, STATUS_PUBLISHED, STATUS_FAILED}) == 3


def test_request_hash_is_order_insensitive_but_value_sensitive() -> None:
    a = {"name": "Hi", "subject": "Hello"}
    b = {"subject": "Hello", "name": "Hi"}
    assert _request_hash(a) == _request_hash(b)
    assert _request_hash(a) != _request_hash({"name": "Hi", "subject": "Different"})
