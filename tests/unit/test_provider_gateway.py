"""Provider gateway contract: eligibility, capacity, routing, retry and adapters.

These tests cover the Stage 5 exit gate without a database: eligibility and
routing are pure functions over account facts, capacity reservation is the
account-level quota boundary, retry classification refuses to resubmit an
ambiguous attempt, and both the mock and Resend adapters are exercised against
simulated provider outcomes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.db.models import ProviderAccount
from app.db.models.provider import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_DISABLED,
    MESSAGE_CLASS_MARKETING,
    MESSAGE_CLASS_TRANSACTIONAL,
)
from app.domain.gateway import capacity, eligibility, retry, routing
from app.providers.contract import (
    HEALTH_DEGRADED,
    HEALTH_UNHEALTHY,
    HEALTH_UNKNOWN,
    MessageClass,
    OutboundMessage,
    ProviderTimeoutError,
    Secret,
    SubmitOutcome,
    SubmitResult,
)
from app.providers.mock import MOCK_PROVIDER_NAME, MockProviderAdapter, timeout_result
from app.providers.registry import available_providers, get_adapter, is_known_provider
from app.providers.resend import ResendProviderAdapter, _classify_send

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
ELIGIBILITY_TTL = 7 * 24 * 3600
CAPACITY_TTL = 24 * 3600


def _account(**overrides: object) -> ProviderAccount:
    """A marketing-eligible, healthy, freshly verified account in memory."""
    account = ProviderAccount(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        provider="mock",
        external_account_ref="acct",
        display_name="",
        status=ACCOUNT_STATUS_ACTIVE,
        eligible_message_classes=[MESSAGE_CLASS_MARKETING],
        sender_domains=["example.com"],
        limits={"daily_limit": 100, "monthly_limit": 3000},
        quota_state={"daily_used": 0, "monthly_used": 0},
        health_state="healthy",
        eligibility_verified_at=NOW - timedelta(hours=1),
        quota_refreshed_at=NOW - timedelta(hours=1),
    )
    for key, value in overrides.items():
        setattr(account, key, value)
    return account


def _evaluate(account: ProviderAccount) -> eligibility.EligibilityDecision:
    return eligibility.evaluate_account(
        account,
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=ELIGIBILITY_TTL,
        capacity_ttl_seconds=CAPACITY_TTL,
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


def _response(status: int, json_body: dict | None = None, headers: dict | None = None):
    return httpx.Response(status, json=json_body, headers=headers or {})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ eligibility
def test_eligible_account_passes() -> None:
    assert _evaluate(_account()).eligible is True


def test_transactional_only_account_never_carries_marketing() -> None:
    account = _account(eligible_message_classes=[MESSAGE_CLASS_TRANSACTIONAL])
    decision = _evaluate(account)
    assert decision.eligible is False
    assert decision.reason == eligibility.EXCLUSION_CLASS_NOT_ELIGIBLE


def test_unverified_marketing_eligibility_is_excluded() -> None:
    account = _account(eligibility_verified_at=None)
    decision = _evaluate(account)
    assert decision.reason == eligibility.EXCLUSION_ELIGIBILITY_UNVERIFIED


def test_stale_eligibility_is_excluded() -> None:
    account = _account(eligibility_verified_at=NOW - timedelta(days=30))
    assert _evaluate(account).reason == eligibility.EXCLUSION_ELIGIBILITY_STALE


def test_unhealthy_account_is_excluded() -> None:
    account = _account(health_state=HEALTH_UNHEALTHY)
    assert _evaluate(account).reason == eligibility.EXCLUSION_UNHEALTHY


def test_stale_capacity_is_excluded() -> None:
    account = _account(quota_refreshed_at=NOW - timedelta(days=5))
    assert _evaluate(account).reason == eligibility.EXCLUSION_CAPACITY_STALE


def test_unknown_capacity_is_excluded() -> None:
    account = _account(limits={})
    assert _evaluate(account).reason == eligibility.EXCLUSION_CAPACITY_UNKNOWN


def test_exhausted_quota_is_excluded() -> None:
    account = _account(
        limits={"daily_limit": 10, "monthly_limit": 100},
        quota_state={"daily_used": 10, "monthly_used": 10},
    )
    assert _evaluate(account).reason == eligibility.EXCLUSION_QUOTA_EXHAUSTED


def test_disabled_account_is_excluded_before_other_rules() -> None:
    account = _account(status=ACCOUNT_STATUS_DISABLED, eligible_message_classes=[])
    assert _evaluate(account).reason == eligibility.EXCLUSION_NOT_ACTIVE


def test_marketing_verified_ignores_capacity_but_requires_fresh_verification() -> None:
    stale_capacity = _account(quota_refreshed_at=None)
    assert (
        eligibility.marketing_verified(
            stale_capacity, now=NOW, eligibility_ttl_seconds=ELIGIBILITY_TTL
        )
        is True
    )
    assert (
        eligibility.marketing_capacity_fresh(
            stale_capacity, now=NOW, capacity_ttl_seconds=CAPACITY_TTL
        )
        is False
    )


# -------------------------------------------------------- capacity / quota unit
def test_capacity_facts_are_read_from_the_account_only() -> None:
    account = _account(
        limits={"daily_limit": 5, "monthly_limit": 50},
        quota_state={"daily_used": 1, "monthly_used": 1},
    )
    facts = capacity.capacity_from_account(account)
    assert facts.daily_remaining == 4
    assert facts.monthly_remaining == 49


def test_unknown_capacity_blocks_reservation() -> None:
    account = _account(limits={})
    assert capacity.reserve_capacity(account, now=NOW) is False
    assert account.quota_state.get("daily_used") in (None, 0)


def test_reservation_uses_account_counters_and_respects_the_daily_limit() -> None:
    account = _account(
        limits={"daily_limit": 2}, quota_state={"daily_used": 0, "monthly_used": 0}
    )
    assert capacity.reserve_capacity(account, now=NOW) is True
    assert capacity.reserve_capacity(account, now=NOW) is True
    # The third reservation is refused: quota belongs to the account, and adding
    # credentials does not create headroom (SPEC.md invariant 3).
    assert capacity.reserve_capacity(account, now=NOW) is False
    assert account.quota_state["daily_used"] == 2


def test_reservation_returns_false_when_a_limit_is_already_exhausted() -> None:
    account = _account(
        limits={"daily_limit": 10, "monthly_limit": 5},
        quota_state={"daily_used": 0, "monthly_used": 5},
    )
    assert capacity.reserve_capacity(account, now=NOW) is False


# --------------------------------------------------------------------- routing
def test_routing_selects_the_highest_priority_account_deterministically() -> None:
    low = _account(limits={"routing_priority": 200, "daily_limit": 100, "monthly_limit": 3000})
    high = _account(limits={"routing_priority": 10, "daily_limit": 100, "monthly_limit": 3000})
    decision = routing.select_account(
        [low, high],
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=ELIGIBILITY_TTL,
        capacity_ttl_seconds=CAPACITY_TTL,
    )
    assert decision.account is high
    assert decision.selected is True


def test_routing_prefers_the_account_with_more_remaining_headroom() -> None:
    small = _account(
        limits={"daily_limit": 100, "monthly_limit": 100},
        quota_state={"daily_used": 0, "monthly_used": 90},
    )
    large = _account(
        limits={"daily_limit": 100, "monthly_limit": 1000},
        quota_state={"daily_used": 0, "monthly_used": 10},
    )
    decision = routing.select_account(
        [small, large],
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=ELIGIBILITY_TTL,
        capacity_ttl_seconds=CAPACITY_TTL,
    )
    assert decision.account is large


def test_routing_reports_an_exclusion_reason_per_ineligible_account() -> None:
    healthy = _account()
    transactional_only = _account(eligible_message_classes=[MESSAGE_CLASS_TRANSACTIONAL])
    decision = routing.select_account(
        [healthy, transactional_only],
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=ELIGIBILITY_TTL,
        capacity_ttl_seconds=CAPACITY_TTL,
    )
    assert decision.account is healthy
    reasons = {item.reason for item in decision.exclusions}
    assert eligibility.EXCLUSION_CLASS_NOT_ELIGIBLE in reasons


def test_routing_excludes_an_account_whose_sender_domain_is_not_configured() -> None:
    account = _account(sender_domains=["example.com"])
    decision = routing.select_account(
        [account],
        message_class=MESSAGE_CLASS_MARKETING,
        now=NOW,
        eligibility_ttl_seconds=ELIGIBILITY_TTL,
        capacity_ttl_seconds=CAPACITY_TTL,
        from_domain="other.com",
    )
    assert decision.selected is False
    assert decision.exclusions[0].reason == eligibility.EXCLUSION_SENDER_DOMAIN


def test_paused_decision_ranks_nothing_and_is_tenant_level() -> None:
    decision = routing.paused_decision("operator hold")
    assert decision.paused is True
    assert decision.pause_reason == "operator hold"
    assert decision.selected is False
    assert decision.exclusions == []


# ----------------------------------------------------------------------- retry
def test_accepted_outcome_is_terminal() -> None:
    decision = retry.classify(
        SubmitResult(outcome=SubmitOutcome.ACCEPTED),
        attempt_no=1,
        policy=retry.RetryPolicy(),
    )
    assert decision.retry is False
    assert decision.needs_reconcile is False


def test_ambiguous_outcome_reconciles_and_never_retries() -> None:
    decision = retry.classify(
        SubmitResult(outcome=SubmitOutcome.AMBIGUOUS, error_class="timeout"),
        attempt_no=1,
        policy=retry.RetryPolicy(),
    )
    assert decision.retry is False
    assert decision.needs_reconcile is True
    assert decision.hold_routing is False


def test_transient_rejection_retries_only_up_to_the_attempt_cap() -> None:
    policy = retry.RetryPolicy(max_attempts=3)
    result = SubmitResult(
        outcome=SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION, error_class="server_error"
    )
    first = retry.classify(result, attempt_no=1, policy=policy)
    assert first.retry is True
    assert first.delay_seconds is not None
    assert retry.classify(result, attempt_no=3, policy=policy).retry is False


def test_provider_retry_after_is_honoured() -> None:
    result = SubmitResult(
        outcome=SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION,
        error_class="rate_limit",
        retry_after_seconds=120,
    )
    decision = retry.classify(result, attempt_no=1, policy=retry.RetryPolicy())
    assert decision.delay_seconds == 120
    assert decision.hold_routing is True


def test_policy_error_holds_routing_and_opens_the_circuit() -> None:
    decision = retry.classify(
        SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION, error_class="policy"
        ),
        attempt_no=1,
        policy=retry.RetryPolicy(),
    )
    assert decision.retry is False
    assert decision.hold_routing is True
    assert decision.open_circuit is True


def test_circuit_health_mapping_labels_only_serious_classes() -> None:
    assert retry.circuit_health_for("auth") == HEALTH_UNHEALTHY
    assert retry.circuit_health_for("quota") == HEALTH_DEGRADED
    assert retry.circuit_health_for("server_error") is None


def test_backoff_is_deterministic_and_capped() -> None:
    policy = retry.RetryPolicy(base_delay_seconds=30, max_delay_seconds=60)
    assert policy.backoff(2, jitter_key="server_error") == policy.backoff(
        2, jitter_key="server_error"
    )
    assert policy.backoff(20, jitter_key="server_error") <= 60


# ---------------------------------------------------------------- mock adapter
async def test_mock_adapter_satisfies_the_common_contract() -> None:
    adapter = MockProviderAdapter()
    verification = await adapter.verify_account(Secret("key"), "acct")
    assert verification.valid is True
    assert verification.sender_domains == ["example.com"]

    snapshot = await adapter.refresh_capacity(Secret("key"))
    # The mock never invents a quota: unknown stays unknown.
    assert snapshot.daily_limit is None
    assert snapshot.monthly_limit is None

    message = _message()
    result = await adapter.send(Secret("key"), message, "idem-1")
    assert result.accepted is True
    assert adapter.sent == [message]


async def test_mock_adapter_scripts_simulated_failures() -> None:
    adapter = MockProviderAdapter(
        script=[
            timeout_result(),
            SubmitResult(outcome=SubmitOutcome.AMBIGUOUS, error_class="timeout"),
        ]
    )
    with pytest.raises(ProviderTimeoutError):
        await adapter.send(Secret("key"), _message(), "idem-1")
    ambiguous = await adapter.send(Secret("key"), _message(), "idem-1")
    assert ambiguous.outcome is SubmitOutcome.AMBIGUOUS


async def test_mock_adapter_is_labelled_and_cannot_send_real_mail() -> None:
    adapter = MockProviderAdapter()
    assert adapter.name == MOCK_PROVIDER_NAME
    assert adapter.is_mock is True
    assert adapter.enqueues_real_messages is False


def test_mock_webhook_signature_verification() -> None:
    adapter = MockProviderAdapter()
    secret = Secret("shared")
    body = b'{"id":"e1","type":"email.delivered","data":{}}'
    signature = hmac.new(b"shared", body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook({"x-mock-signature": signature}, body, secret) is True
    assert adapter.verify_webhook({"x-mock-signature": "nope"}, body, secret) is False
    assert adapter.verify_webhook({}, body, secret) is False


async def test_mock_reconcile_reports_not_found_without_a_message_id() -> None:
    adapter = MockProviderAdapter(reconcile_state="not_found")
    result = await adapter.reconcile(Secret("key"), None, "idem-1")
    assert result.state == "not_found"
    assert result.resolved is False


# --------------------------------------------------------------- resend mapping
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, SubmitOutcome.ACCEPTED),
        (202, SubmitOutcome.ACCEPTED),
        (422, SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION),
        (401, SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION),
        (403, SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION),
        (500, SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION),
        (503, SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION),
    ],
)
def test_resend_maps_http_status_to_submit_outcome(status: int, expected: SubmitOutcome) -> None:
    result = _classify_send(_response(status, {"id": "msg_1"}))
    assert result.outcome is expected


def test_resend_401_is_an_auth_rejection() -> None:
    result = _classify_send(_response(401, {"message": "invalid api key"}))
    assert result.outcome is SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION
    assert result.error_class == "auth"


def test_resend_403_is_a_policy_rejection() -> None:
    result = _classify_send(_response(403, {"name": "domain_not_verified"}))
    assert result.outcome is SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION
    assert result.error_class == "policy"


def test_resend_429_reports_quota_class_and_retry_after() -> None:
    result = _classify_send(
        _response(429, {"name": "daily_quota_exceeded"}, {"retry-after": "42"})
    )
    assert result.outcome is SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION
    assert result.error_class == "quota_daily"
    assert result.retry_after_seconds == 42


def test_resend_429_without_a_quota_hint_is_a_rate_limit() -> None:
    assert _classify_send(_response(429)).error_class == "rate_limit"


def test_resend_409_idempotency_conflict_is_permanent() -> None:
    result = _classify_send(_response(409, {"name": "invalid_idempotency_key"}))
    assert result.outcome is SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION
    assert result.error_class == "idempotency_conflict"


def test_resend_409_concurrency_is_transient() -> None:
    result = _classify_send(_response(409, {"name": "concurrent_idempotent_requests"}))
    assert result.outcome is SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION
    assert result.error_class == "concurrency"


async def test_resend_verify_account_reports_only_verified_domains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"name": "example.com", "status": "verified"},
                    {"name": "pending.example", "status": "pending"},
                ]
            },
        )

    client = _client(handler)
    adapter = ResendProviderAdapter(client=client)
    verification = await adapter.verify_account(Secret("key"), "acct")
    await client.aclose()
    assert verification.valid is True
    assert verification.sender_domains == ["example.com"]
    # The adapter reports observable facts only; it never grants eligibility.
    assert verification.eligible_message_classes == frozenset()


async def test_resend_verify_account_timeout_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    client = _client(handler)
    adapter = ResendProviderAdapter(client=client)
    verification = await adapter.verify_account(Secret("key"), "acct")
    await client.aclose()
    assert verification.valid is False
    assert verification.health_state == HEALTH_UNKNOWN


async def test_resend_refresh_capacity_stays_unknown_without_headers() -> None:
    client = _client(lambda request: httpx.Response(200, json={"data": []}))
    adapter = ResendProviderAdapter(client=client)
    snapshot = await adapter.refresh_capacity(Secret("key"))
    await client.aclose()
    assert snapshot.daily_limit is None
    assert snapshot.monthly_limit is None
    assert snapshot.source == "resend:response-headers"


async def test_resend_refresh_capacity_reads_provider_headers() -> None:
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"data": []},
            headers={
                "x-resend-daily-quota": "500",
                "x-resend-monthly-quota": "15000",
                "ratelimit-limit": "10",
            },
        )
    )
    adapter = ResendProviderAdapter(client=client)
    snapshot = await adapter.refresh_capacity(Secret("key"))
    await client.aclose()
    assert snapshot.daily_limit == 500
    assert snapshot.monthly_limit == 15000
    assert snapshot.rate_per_second == 10


async def test_resend_send_timeout_surfaces_as_ambiguous_risk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no response")

    client = _client(handler)
    adapter = ResendProviderAdapter(client=client)
    with pytest.raises(ProviderTimeoutError):
        await adapter.send(Secret("key"), _message(), "idem-1")
    await client.aclose()


async def test_resend_reconcile_without_a_message_id_cannot_resolve() -> None:
    client = _client(lambda request: httpx.Response(404, json={}))
    adapter = ResendProviderAdapter(client=client)
    result = await adapter.reconcile(Secret("key"), None, "idem-1")
    await client.aclose()
    assert result.state == "not_found"
    assert result.resolved is False


async def test_resend_reconcile_looks_up_a_known_message_id() -> None:
    client = _client(lambda request: httpx.Response(200, json={"last_event": "delivered"}))
    adapter = ResendProviderAdapter(client=client)
    result = await adapter.reconcile(Secret("key"), "msg_1", "idem-1")
    await client.aclose()
    assert result.state == "delivered"
    assert result.resolved is True


def test_resend_webhook_signature_round_trip() -> None:
    raw_key = b"0123456789abcdef0123456789abcdef"
    secret_value = "whsec_" + base64.b64encode(raw_key).decode()
    adapter = ResendProviderAdapter()
    body = b'{"type":"email.delivered"}'
    message_id = "msg_1"
    timestamp = str(int(time.time()))
    signed = f"{message_id}.{timestamp}.".encode() + body
    signature = base64.b64encode(hmac.new(raw_key, signed, hashlib.sha256).digest()).decode()
    headers = {
        "svix-id": message_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{signature}",
    }
    assert adapter.verify_webhook(headers, body, Secret(secret_value)) is True
    # A tampered body must fail verification.
    assert adapter.verify_webhook(headers, body + b"x", Secret(secret_value)) is False
    # A missing signature header must fail closed.
    assert adapter.verify_webhook({}, body, Secret(secret_value)) is False


# -------------------------------------------------------------------- registry
def test_registry_resolves_registered_providers_only() -> None:
    assert is_known_provider(MOCK_PROVIDER_NAME) is True
    assert is_known_provider("resend") is True
    assert is_known_provider("does-not-exist") is False
    assert get_adapter("mock").name == MOCK_PROVIDER_NAME
    assert available_providers() == sorted(available_providers())
