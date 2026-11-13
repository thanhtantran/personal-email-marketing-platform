"""Capacity-aware routing.

Routing chooses among accounts that are verified eligible for the message class.
It is deterministic -- highest routing priority wins, ties break on the largest
remaining headroom, then on configured weight, with the account id as a stable
final tiebreak. Random round-robin is deliberately not used, and every account
left out is reported with its exclusion reason so the owner can see why a send
did not route (SPEC.md sections 6 and 10).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.db.models import ProviderAccount
from app.domain.gateway import eligibility
from app.domain.gateway.capacity import capacity_from_account

#: Default routing priority when an account records none (lower wins).
DEFAULT_PRIORITY = 100
DEFAULT_WEIGHT = 1


@dataclass(frozen=True)
class RoutingExclusion:
    """Why one account was not selected for this decision."""

    account_id: uuid.UUID
    provider: str
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """The ranked eligible accounts plus the reasons others were excluded.

    ``ranked`` is empty when nothing may carry the message; ``paused`` records a
    global marketing pause, which is a tenant-level stop rather than an
    account-level exclusion.
    """

    ranked: list[ProviderAccount] = field(default_factory=list)
    exclusions: list[RoutingExclusion] = field(default_factory=list)
    paused: bool = False
    pause_reason: str | None = None

    @property
    def account(self) -> ProviderAccount | None:
        return self.ranked[0] if self.ranked else None

    @property
    def selected(self) -> bool:
        return bool(self.ranked)

    def exclusion_reasons(self) -> list[dict]:
        """Operator-visible reasons, one entry per excluded account."""
        return [
            {
                "account_id": str(item.account_id),
                "provider": item.provider,
                "reason": item.reason,
                "detail": item.detail,
            }
            for item in self.exclusions
        ]


def paused_decision(reason: str | None) -> RoutingDecision:
    return RoutingDecision(ranked=[], exclusions=[], paused=True, pause_reason=reason)


def _priority(account: ProviderAccount) -> int:
    value = (account.limits or {}).get("routing_priority")
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY


def _weight(account: ProviderAccount) -> int:
    value = (account.limits or {}).get("routing_weight")
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT


def _headroom(account: ProviderAccount) -> tuple[int, int]:
    facts = capacity_from_account(account)
    monthly = facts.monthly_remaining if facts.monthly_remaining is not None else -1
    daily = facts.daily_remaining if facts.daily_remaining is not None else -1
    return monthly, daily


def _sort_key(account: ProviderAccount) -> tuple:
    monthly, daily = _headroom(account)
    return (_priority(account), -monthly, -daily, -_weight(account), str(account.id))


def select_account(
    accounts: Sequence[ProviderAccount],
    *,
    message_class: str,
    now: datetime,
    eligibility_ttl_seconds: int,
    capacity_ttl_seconds: int,
    from_domain: str | None = None,
) -> RoutingDecision:
    """Rank the accounts that may carry ``message_class`` and exclude the rest."""
    eligible: list[ProviderAccount] = []
    exclusions: list[RoutingExclusion] = []
    for account in accounts:
        decision = eligibility.evaluate_account(
            account,
            message_class=message_class,
            now=now,
            eligibility_ttl_seconds=eligibility_ttl_seconds,
            capacity_ttl_seconds=capacity_ttl_seconds,
        )
        if not decision.eligible:
            exclusions.append(
                RoutingExclusion(
                    account.id, account.provider, decision.reason or "", decision.detail
                )
            )
            continue
        if (
            from_domain
            and account.sender_domains
            and from_domain not in set(account.sender_domains)
        ):
            exclusions.append(
                RoutingExclusion(
                    account.id,
                    account.provider,
                    eligibility.EXCLUSION_SENDER_DOMAIN,
                    f"domain '{from_domain}' is not configured on the account",
                )
            )
            continue
        eligible.append(account)

    if not eligible:
        return RoutingDecision(ranked=[], exclusions=exclusions)
    return RoutingDecision(ranked=sorted(eligible, key=_sort_key), exclusions=exclusions)
