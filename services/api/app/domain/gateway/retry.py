"""Retry classification and circuit-breaker policy.

Only a *definitive transient* rejection is retried, and only up to the attempt
cap. An ambiguous outcome is never retried automatically: reconciliation must
prove the earlier request was not accepted first, because a blind resubmit could
deliver a duplicate (SPEC.md invariant 6). Provider auth, policy and quota errors
additionally hold routing for the account, and the strictest of them open the
circuit by marking the account unhealthy so it stops receiving traffic and the
owner can see why (SPEC.md section 10).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.providers.contract import (
    HEALTH_DEGRADED,
    HEALTH_UNHEALTHY,
    SubmitOutcome,
    SubmitResult,
)

#: Error classes that hold routing for the account until it is re-verified.
HOLD_ROUTING_CLASSES: frozenset[str] = frozenset(
    {
        "auth",
        "policy",
        "quota",
        "quota_daily",
        "quota_monthly",
        "rate_limit",
        "domain_unverified",
        "idempotency_conflict",
    }
)

#: Error classes that hold routing *and* open the circuit (account unhealthy).
CIRCUIT_OPENING_CLASSES: frozenset[str] = frozenset(
    {"auth", "policy", "domain_unverified"}
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: int = 30
    max_delay_seconds: int = 3600

    def backoff(
        self,
        attempt_no: int,
        *,
        retry_after_seconds: int | None = None,
        jitter_key: str = "",
    ) -> int:
        """Seconds to wait before the next attempt.

        A provider ``Retry-After`` is honoured as-is (bounded by the cap);
        otherwise exponential backoff is used with **deterministic** jitter so a
        retried worker computes the same instant rather than drifting.
        """
        if retry_after_seconds is not None and retry_after_seconds > 0:
            return min(retry_after_seconds, self.max_delay_seconds)
        exponent = max(attempt_no - 1, 0)
        ceiling = min(self.base_delay_seconds * (2**exponent), self.max_delay_seconds)
        half = max(ceiling // 2, 1)
        digest = hashlib.sha256(f"{jitter_key}:{attempt_no}".encode()).hexdigest()
        return min(ceiling, half + int(digest[:8], 16) % half)


@dataclass(frozen=True)
class RetryDecision:
    """What the worker may do with one submission outcome."""

    retry: bool
    delay_seconds: int | None
    hold_routing: bool
    open_circuit: bool
    needs_reconcile: bool
    reason: str | None


def classify(result: SubmitResult, *, attempt_no: int, policy: RetryPolicy) -> RetryDecision:
    """Turn one normalized ``SubmitResult`` into a retry/routing decision."""
    error_class = result.error_class
    if result.outcome is SubmitOutcome.ACCEPTED:
        return RetryDecision(False, None, False, False, False, None)

    if result.outcome is SubmitOutcome.AMBIGUOUS:
        # Reconcile before any retry; an ambiguous result is never resubmitted.
        return RetryDecision(False, None, False, False, True, error_class or "ambiguous")

    hold = error_class in HOLD_ROUTING_CLASSES
    open_circuit = error_class in CIRCUIT_OPENING_CLASSES

    if result.outcome is SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION:
        return RetryDecision(False, None, hold, open_circuit, False, error_class)

    retry = attempt_no < policy.max_attempts
    delay = (
        policy.backoff(
            attempt_no,
            retry_after_seconds=result.retry_after_seconds,
            jitter_key=error_class or "transient",
        )
        if retry
        else None
    )
    return RetryDecision(retry, delay, hold, open_circuit, False, error_class)


def circuit_health_for(error_class: str | None) -> str | None:
    """The account health state a provider error should force, if any.

    Returns ``None`` for errors that must not change health, so a transient
    server error does not silently disable an otherwise healthy account.
    """
    if error_class in CIRCUIT_OPENING_CLASSES:
        return HEALTH_UNHEALTHY
    if error_class in HOLD_ROUTING_CLASSES:
        return HEALTH_DEGRADED
    return None
