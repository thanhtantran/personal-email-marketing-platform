"""Capacity facts, local quota reservations and rate gates.

Capacity numbers are **external facts**: an account's caps come from provider
verification or an operator record, and a missing cap is treated as *unknown* and
blocks routing rather than being invented (SPEC.md invariant 9). The reservation
counter is local accounting that stops two workers from over-committing the same
account, and it is attached to the account -- never to a credential -- so adding
an API key cannot multiply quota (SPEC.md invariant 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CapacityFacts:
    """The capacity facts routing and reservation act on."""

    daily_limit: int | None
    daily_used: int
    monthly_limit: int | None
    monthly_used: int
    rate_per_second: int | None
    domain_rate_per_second: int | None

    @property
    def known(self) -> bool:
        """At least one provider-confirmed cap exists.

        A provider that exposes no usage/cap figure yields ``False``; the gateway
        never substitutes a guessed number (SPEC.md invariant 9).
        """
        return self.daily_limit is not None or self.monthly_limit is not None

    @property
    def daily_remaining(self) -> int | None:
        if self.daily_limit is None:
            return None
        return max(self.daily_limit - self.daily_used, 0)

    @property
    def monthly_remaining(self) -> int | None:
        if self.monthly_limit is None:
            return None
        return max(self.monthly_limit - self.monthly_used, 0)

    @property
    def exhausted(self) -> bool:
        return self.daily_remaining == 0 or self.monthly_remaining == 0


def capacity_from_account(account: object) -> CapacityFacts:
    """Read capacity facts from an account's ``limits`` and ``quota_state``."""
    limits = dict(getattr(account, "limits", None) or {})
    state = dict(getattr(account, "quota_state", None) or {})
    return CapacityFacts(
        daily_limit=_int_or_none(limits.get("daily_limit")),
        daily_used=_int_or_none(state.get("daily_used")) or 0,
        monthly_limit=_int_or_none(limits.get("monthly_limit")),
        monthly_used=_int_or_none(state.get("monthly_used")) or 0,
        rate_per_second=_int_or_none(limits.get("rate_per_second")),
        domain_rate_per_second=_int_or_none(limits.get("domain_rate_per_second")),
    )


def rolled_state(account: object, *, now: datetime) -> dict:
    """Return the account's usage counters, resetting rolled-over periods."""
    state = dict(getattr(account, "quota_state", None) or {})
    moment = now.astimezone(UTC)
    day_key = moment.date().isoformat()
    month_key = f"{moment.year:04d}-{moment.month:02d}"
    if state.get("period_day") != day_key:
        state["period_day"] = day_key
        state["daily_used"] = 0
    if state.get("period_month") != month_key:
        state["period_month"] = month_key
        state["monthly_used"] = 0
    return state


def reserve_capacity(account: object, *, now: datetime, amount: int = 1) -> bool:
    """Check remaining capacity and commit a reservation of ``amount``.

    The caller must hold the account row ``FOR UPDATE`` so the read-check-write
    is serialized across workers. Returns ``False`` (and changes nothing) when the
    account has no known cap or not enough headroom left.
    """
    facts = capacity_from_account(account)
    if not facts.known or facts.exhausted:
        return False
    state = rolled_state(account, now=now)
    daily_used = _int_or_none(state.get("daily_used")) or 0
    monthly_used = _int_or_none(state.get("monthly_used")) or 0
    if facts.daily_limit is not None and daily_used + amount > facts.daily_limit:
        return False
    if facts.monthly_limit is not None and monthly_used + amount > facts.monthly_limit:
        return False
    state["daily_used"] = daily_used + amount
    state["monthly_used"] = monthly_used + amount
    account.quota_state = state  # type: ignore[attr-defined]
    return True


class RateGate:
    """Fixed-window rate accounting per account and per sender domain.

    Redis is only a coordination cache; when it is unavailable, or no rate is
    recorded for the scope, the gate allows the send instead of blocking the whole
    platform. Durable quota reservation and provider-side throttling still apply
    (ARCHITECTURE.md section 7).
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    async def allow(
        self,
        *,
        scope: str,
        identifier: str,
        per_second: int | None,
        now: datetime,
    ) -> bool:
        if self._redis is None or not per_second or per_second <= 0:
            return True
        bucket = f"gateway:rate:{scope}:{identifier}:{int(now.timestamp())}"
        count = await self._redis.incr(bucket)
        if count == 1:
            await self._redis.expire(bucket, 2)
        return count <= per_second
