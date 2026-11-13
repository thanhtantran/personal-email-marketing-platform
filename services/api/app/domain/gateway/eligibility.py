"""Per-message-class eligibility and routing exclusion reasons.

Eligibility is an explicit, verified capability with a timestamp -- it is never
inferred from another class or from the presence of credentials. When routing
leaves an account out it always records *why*, so an operator can act instead of
guessing (SPEC.md invariants 4 and 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.db.models.provider import ACCOUNT_STATUS_ACTIVE, MESSAGE_CLASS_MARKETING
from app.domain.gateway.capacity import capacity_from_account
from app.providers.contract import HEALTH_HEALTHY

# Stable machine codes surfaced as "routing exclusion reason".
EXCLUSION_NOT_ACTIVE = "account_not_active"
EXCLUSION_CLASS_NOT_ELIGIBLE = "message_class_not_eligible"
EXCLUSION_ELIGIBILITY_UNVERIFIED = "eligibility_unverified"
EXCLUSION_ELIGIBILITY_STALE = "eligibility_stale"
EXCLUSION_UNHEALTHY = "account_not_healthy"
EXCLUSION_CAPACITY_UNKNOWN = "capacity_unknown"
EXCLUSION_CAPACITY_STALE = "capacity_stale"
EXCLUSION_QUOTA_EXHAUSTED = "quota_exhausted"
EXCLUSION_RATE_LIMITED = "account_rate_exceeded"
EXCLUSION_DOMAIN_RATE = "domain_rate_exceeded"
EXCLUSION_SENDER_DOMAIN = "sender_domain_not_allowed"
EXCLUSION_CREDENTIAL = "credential_unavailable"


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str | None = None
    detail: str | None = None


def is_stale(observed_at: datetime | None, *, now: datetime, ttl_seconds: int) -> bool:
    """Whether an observation is missing or older than its allowed lifetime."""
    if observed_at is None:
        return True
    return observed_at <= now - timedelta(seconds=ttl_seconds)


def marketing_verified(account: object, *, now: datetime, eligibility_ttl_seconds: int) -> bool:
    """Whether the account is verified (and fresh) for marketing sends.

    Capacity, health and remaining quota are intentionally not part of this
    predicate, so launch validation can report "no marketing-verified account"
    separately from "capacity stale/unknown" (``validation.py`` codes).
    """
    classes = set(getattr(account, "eligible_message_classes", None) or [])
    if getattr(account, "status", None) != ACCOUNT_STATUS_ACTIVE:
        return False
    if MESSAGE_CLASS_MARKETING not in classes:
        return False
    return not is_stale(
        getattr(account, "eligibility_verified_at", None),
        now=now,
        ttl_seconds=eligibility_ttl_seconds,
    )


def marketing_capacity_fresh(
    account: object, *, now: datetime, capacity_ttl_seconds: int
) -> bool:
    """Whether a marketing-verified account has known, fresh, non-exhausted quota."""
    if is_stale(
        getattr(account, "quota_refreshed_at", None),
        now=now,
        ttl_seconds=capacity_ttl_seconds,
    ):
        return False
    facts = capacity_from_account(account)
    return facts.known and not facts.exhausted


def evaluate_account(
    account: object,
    *,
    message_class: str,
    now: datetime,
    eligibility_ttl_seconds: int,
    capacity_ttl_seconds: int,
) -> EligibilityDecision:
    """Decide whether one account may carry a message of ``message_class``.

    The first failing rule wins. The checks are ordered so the most actionable
    reason is reported first (operator state, then class, then verification
    freshness, then health and capacity).
    """
    status = getattr(account, "status", None)
    if status != ACCOUNT_STATUS_ACTIVE:
        return EligibilityDecision(False, EXCLUSION_NOT_ACTIVE, f"status={status}")

    classes = set(getattr(account, "eligible_message_classes", None) or [])
    if message_class not in classes:
        return EligibilityDecision(
            False, EXCLUSION_CLASS_NOT_ELIGIBLE, f"declared={sorted(classes)}"
        )

    verified_at = getattr(account, "eligibility_verified_at", None)
    if verified_at is None:
        return EligibilityDecision(
            False, EXCLUSION_ELIGIBILITY_UNVERIFIED, f"no verification for '{message_class}'"
        )
    if is_stale(verified_at, now=now, ttl_seconds=eligibility_ttl_seconds):
        return EligibilityDecision(
            False, EXCLUSION_ELIGIBILITY_STALE, f"verified_at={verified_at.isoformat()}"
        )

    health = getattr(account, "health_state", None)
    if health != HEALTH_HEALTHY:
        return EligibilityDecision(False, EXCLUSION_UNHEALTHY, f"health_state={health}")

    refreshed_at = getattr(account, "quota_refreshed_at", None)
    if refreshed_at is None:
        return EligibilityDecision(
            False, EXCLUSION_CAPACITY_UNKNOWN, "no capacity refresh recorded"
        )
    if is_stale(refreshed_at, now=now, ttl_seconds=capacity_ttl_seconds):
        return EligibilityDecision(
            False, EXCLUSION_CAPACITY_STALE, f"refreshed_at={refreshed_at.isoformat()}"
        )

    facts = capacity_from_account(account)
    if not facts.known:
        return EligibilityDecision(
            False, EXCLUSION_CAPACITY_UNKNOWN, "provider exposes no capacity limit"
        )
    if facts.exhausted:
        return EligibilityDecision(
            False,
            EXCLUSION_QUOTA_EXHAUSTED,
            f"daily_left={facts.daily_remaining} monthly_left={facts.monthly_remaining}",
        )
    return EligibilityDecision(True)
