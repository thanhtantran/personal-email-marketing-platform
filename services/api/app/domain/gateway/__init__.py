"""Provider gateway domain.

Public surface: eligibility and routing decisions, capacity reservation and rate
gates, retry/circuit policy, and the orchestrating :class:`ProviderGateway` that
campaign dispatch uses to talk to a provider (SPEC.md sections 5 and 6).
"""

from __future__ import annotations

from app.domain.gateway.capacity import (
    CapacityFacts,
    RateGate,
    capacity_from_account,
    reserve_capacity,
)
from app.domain.gateway.eligibility import (
    EligibilityDecision,
    evaluate_account,
    marketing_capacity_fresh,
    marketing_verified,
)
from app.domain.gateway.retry import (
    RetryDecision,
    RetryPolicy,
    circuit_health_for,
    classify,
)
from app.domain.gateway.routing import (
    RoutingDecision,
    RoutingExclusion,
    paused_decision,
    select_account,
)
from app.domain.gateway.service import (
    HOLD_REASON_MARKETING_PAUSED,
    STATUS_HELD,
    GatewayStatus,
    ProviderGateway,
    SubmissionReport,
    build_outbound_message,
)

__all__ = [
    "HOLD_REASON_MARKETING_PAUSED",
    "STATUS_HELD",
    "CapacityFacts",
    "EligibilityDecision",
    "GatewayStatus",
    "ProviderGateway",
    "RateGate",
    "RetryDecision",
    "RetryPolicy",
    "RoutingDecision",
    "RoutingExclusion",
    "SubmissionReport",
    "build_outbound_message",
    "capacity_from_account",
    "circuit_health_for",
    "classify",
    "evaluate_account",
    "marketing_capacity_fresh",
    "marketing_verified",
    "paused_decision",
    "reserve_capacity",
    "select_account",
]
