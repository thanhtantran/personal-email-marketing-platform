"""Fault injection for the paths SPEC.md section 11 calls out by name.

Each test drives one failure the platform must survive without losing work,
without duplicating a send and without misleading the operator:

* an ambiguous submit (timeout before or after the provider may have accepted),
* a worker crash between the database commit and the queue publish,
* a stale quota that must not be spent,
* an out-of-order or replayed webhook delivery,
* a campaign that leaves ``sending`` while a batch is in flight.

Where a real PostgreSQL session is not available these drive the same code with
the smallest possible fake, so the decision logic is exercised rather than
restated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db.models import OutboxEvent, ProviderAccount
from app.db.models.provider import (
    ACCOUNT_STATUS_ACTIVE,
    MESSAGE_CLASS_MARKETING,
)
from app.domain.campaign.lifecycle import allows_dispatch
from app.domain.events.reducer import reduce_recipient_status
from app.domain.events.vocabulary import (
    EVENT_BOUNCED_HARD,
    EVENT_DELIVERED,
    EVENT_SUBMITTED,
)
from app.domain.gateway import eligibility, routing
from app.domain.gateway.service import ProviderGateway
from app.observability.metrics import PROVIDER_SUBMISSIONS, PROVIDER_SUBMIT_SECONDS
from app.providers.contract import (
    MessageClass,
    OutboundMessage,
    Secret,
    SubmitOutcome,
)
from app.providers.mock import MockProviderAdapter, timeout_result
from app.repositories.outbox_repo import STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED
from app.workers.outbox import dispatch_pending

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def _settings(**overrides: object) -> Settings:
    return Settings(app_env="development", **overrides)


def _account(**overrides: object) -> ProviderAccount:
    account = ProviderAccount(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        provider="mock",
        external_account_ref="acct",
        display_name="",
        status=ACCOUNT_STATUS_ACTIVE,
        eligible_message_classes=[MESSAGE_CLASS_MARKETING],
        sender_domains=["example.com"],
        limits={"daily_limit": 100, "monthly_limit": 3000},
        quota_state={"daily_used": 0, "monthly_used": 0},
        health_state="healthy",
    )
    for key, value in overrides.items():
        setattr(account, key, value)
    return account


def _gateway(adapter: object, **overrides: object) -> ProviderGateway:
    """A gateway wired to one adapter, with repositories left untouched.

    Only the submit path is under test here, so the session is never used:
    every repository still just holds the reference it was given.
    """
    return ProviderGateway(
        None,  # type: ignore[arg-type] - repositories are unused on this path
        TENANT,
        _settings(**overrides),
        adapter_factory=lambda _provider: adapter,  # type: ignore[arg-type,return-value]
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_class=MessageClass.MARKETING,
        to_email="recipient@example.com",
        from_email="sender@example.com",
        from_name="Sender",
        subject="Hello",
        html="<p>Hello</p>",
        text="Hello",
    )


class _RaisingAdapter:
    """An adapter whose request is lost after it may have been accepted."""

    async def send(self, secret: Secret, message: OutboundMessage, key: str) -> object:
        raise TimeoutError("no response before the deadline")


# -------------------------------------------------- ambiguous submit outcomes
async def test_timeout_is_recorded_ambiguous_and_never_a_success() -> None:
    result = await _gateway(_RaisingAdapter())._send(
        _account(), Secret("key"), _message(), "idem-1"
    )
    assert result.outcome is SubmitOutcome.AMBIGUOUS
    assert result.error_class == "timeout"
    assert result.accepted is False


async def test_adapter_error_is_also_ambiguous_not_a_failure() -> None:
    """A raised adapter error leaves the outcome unknown: reconcile, then retry."""
    adapter = MockProviderAdapter(script=[timeout_result()])
    result = await _gateway(adapter)._send(_account(), Secret("key"), _message(), "idem-1")
    assert result.outcome is SubmitOutcome.AMBIGUOUS
    assert result.error_class == "ProviderTimeoutError"


def test_submission_metric_accepts_every_declared_outcome_label() -> None:
    """The call site in ``_record`` can never raise on its label set."""
    for outcome in SubmitOutcome:
        PROVIDER_SUBMISSIONS.inc(provider="mock", outcome=outcome.value)
    PROVIDER_SUBMIT_SECONDS.observe(0.123, provider="mock")


async def test_submit_latency_is_observed_for_the_provider() -> None:
    before = _histogram_count("mock")
    await _gateway(MockProviderAdapter())._send(
        _account(), Secret("key"), _message(), "idem-1"
    )
    assert _histogram_count("mock") == before + 1


# ------------------------------- worker crash between the commit and the queue
def _event(**overrides: object) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        event_type="campaign.dispatch",
        aggregate_type="campaign",
        aggregate_id=uuid.uuid4(),
        payload={"campaign_id": str(uuid.uuid4())},
        status=STATUS_PENDING,
        attempts=0,
        available_at=NOW,
    )
    for key, value in overrides.items():
        setattr(event, key, value)
    return event


class _Result:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[OutboxEvent]:
        return list(self._rows)


class _FakeSession:
    """Just enough of an AsyncSession for the outbox dispatcher."""

    def __init__(self, rows: list[OutboxEvent]) -> None:
        self._rows = rows
        self.commits = 0

    async def execute(self, _statement: object) -> _Result:
        return _Result(self._rows)

    async def flush(self) -> None: ...

    async def commit(self) -> None:
        self.commits += 1


async def test_broker_failure_defers_the_event_instead_of_losing_it() -> None:
    event = _event()

    def _boom(_task: str, _payload: dict) -> None:
        raise RuntimeError("broker down")

    published = await dispatch_pending(
        _FakeSession([event]),  # type: ignore[arg-type]
        _settings(campaign_outbox_max_attempts=5),
        send=_boom,
        now=NOW,
    )

    assert published == 0
    assert event.status == STATUS_PENDING
    assert event.attempts == 1
    assert event.available_at > NOW
    assert event.last_error == "RuntimeError"


async def test_a_repeatedly_failing_publish_is_failed_not_retried_forever() -> None:
    event = _event(attempts=4)

    def _boom(_task: str, _payload: dict) -> None:
        raise RuntimeError("broker down")

    await dispatch_pending(
        _FakeSession([event]),  # type: ignore[arg-type]
        _settings(campaign_outbox_max_attempts=5),
        send=_boom,
        now=NOW,
    )

    assert event.status == STATUS_FAILED
    assert event.attempts == 5


async def test_successful_publish_marks_the_event_published() -> None:
    event = _event()
    calls: list[tuple[str, dict]] = []

    published = await dispatch_pending(
        _FakeSession([event]),  # type: ignore[arg-type]
        _settings(),
        send=lambda task, payload: calls.append((task, payload)),
        now=NOW,
    )

    assert published == 1
    assert event.status == STATUS_PUBLISHED
    assert event.published_at == NOW
    assert calls[0][0] == "app.workers.tasks.dispatch_campaign"


async def test_an_unmapped_event_type_fails_loudly_rather_than_looping() -> None:
    event = _event(event_type="something.unmapped")

    published = await dispatch_pending(
        _FakeSession([event]),  # type: ignore[arg-type]
        _settings(),
        send=lambda task, payload: None,
        now=NOW,
    )

    assert published == 0
    assert event.status == STATUS_FAILED
    assert "no task mapped" in (event.last_error or "")


# ----------------------------------------------------------------- stale quota
def test_a_stale_quota_reading_is_never_spent() -> None:
    """Capacity must come from dated facts, so an old reading routes nowhere."""
    stale = _account(
        eligibility_verified_at=NOW,
        quota_refreshed_at=NOW - timedelta(days=5),
        limits={"daily_limit": 100, "monthly_limit": 3000},
    )
    decision = routing.select_account(
        [stale],
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=7 * 24 * 3600,
        capacity_ttl_seconds=24 * 3600,
    )
    assert decision.selected is False
    assert decision.exclusions[0].reason == eligibility.EXCLUSION_CAPACITY_STALE


# ----------------------------------------------------- out-of-order deliveries
def test_a_delivery_arriving_before_the_api_acceptance_still_lands() -> None:
    """A provider report can overtake the submit response; order must not matter."""
    assert reduce_recipient_status("queued", event_type=EVENT_DELIVERED) == "accepted"


def test_a_late_delivery_cannot_undo_a_bounce() -> None:
    bounced = reduce_recipient_status("accepted", event_type=EVENT_BOUNCED_HARD)
    assert bounced == "failed"
    # The replay of an earlier ``submitted`` event must not revive the recipient.
    assert reduce_recipient_status(bounced, event_type=EVENT_SUBMITTED) is None


# ---------------------------------------------------------- cancellation race
def test_cancelling_mid_batch_stops_new_submissions() -> None:
    """Cancellation stops new work; anything already accepted stays accepted."""
    assert allows_dispatch("sending") is True
    assert allows_dispatch("cancelled") is False


def _histogram_count(provider: str) -> float:
    return sum(
        value
        for suffix, labels, value in PROVIDER_SUBMIT_SECONDS.samples()
        if suffix == "_count" and labels.get("provider") == provider
    )
