"""Provider adapter contract (SPEC.md section 6).

Campaign logic produces normalized :class:`OutboundMessage` values; only an
adapter in this package turns them into provider-specific requests, and only an
adapter interprets provider-specific responses back into a normalized
:class:`SubmitResult`. Nothing outside this package may assume a provider's
semantics, quota or eligibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class MessageClass(StrEnum):
    """The message class a send belongs to.

    Eligibility is tracked per class: a transactional-only account must never
    receive a marketing send (SPEC.md invariant 4).
    """

    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"


class SubmitOutcome(StrEnum):
    """The four provider outcomes a router and worker may act on."""

    ACCEPTED = "accepted"
    DEFINITIVE_TRANSIENT_REJECTION = "definitive_transient_rejection"
    DEFINITIVE_PERMANENT_REJECTION = "definitive_permanent_rejection"
    AMBIGUOUS = "ambiguous"


#: ACCOUNT health as reported by verification/refresh.
HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_UNHEALTHY = "unhealthy"
HEALTH_UNKNOWN = "unknown"


class ProviderAdapterError(Exception):
    """Base class for adapter-level failures raised before a result is known."""


class ProviderTimeoutError(ProviderAdapterError):
    """The request may have reached the provider; the outcome is unknown.

    A worker must record this as ``unknown`` and reconcile before retrying
    (SPEC.md section 5).
    """


@dataclass(frozen=True)
class Secret:
    """A write-only credential value.

    The value is excluded from ``repr`` so it cannot leak through logs, trace
    attributes or exception messages; use :meth:`reveal` at the single call site
    that needs it.
    """

    value: str = field(repr=False)
    label: str = ""

    def reveal(self) -> str:
        return self.value

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Secret(label={self.label!r}, value=***)"


@dataclass(frozen=True)
class AccountVerification:
    """The observable facts an adapter can confirm about one account."""

    account_ref: str
    valid: bool
    health_state: str
    eligible_message_classes: frozenset[str]
    sender_domains: list[str] = field(default_factory=list)
    #: Which facts came from the provider versus operator-recorded state.
    observed_by: str = "adapter"
    detail: str | None = None


@dataclass(frozen=True)
class CapacitySnapshot:
    """Provider-reported or operator-recorded capacity.

    Any ``None`` limit means **unknown**, which routing treats as blocking. The
    application never invents a quota, and a missing usage API yields unknown
    rather than an inferred number (SPEC.md invariant 9).
    """

    observed_at: datetime
    source: str
    daily_limit: int | None = None
    daily_used: int | None = None
    monthly_limit: int | None = None
    monthly_used: int | None = None
    rate_per_second: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    """A provider-agnostic message ready for submission."""

    message_class: MessageClass
    to_email: str
    from_email: str
    from_name: str
    subject: str
    html: str
    text: str
    reply_to: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmitResult:
    """Normalized result of one submission attempt."""

    outcome: SubmitOutcome
    provider_message_id: str | None = None
    #: Coarse classification used for retry decisions and operator reporting.
    error_class: str | None = None
    response_code: int | None = None
    retry_after_seconds: int | None = None
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome is SubmitOutcome.ACCEPTED


@dataclass(frozen=True)
class NormalizedProviderEvent:
    """A provider webhook event mapped onto platform vocabulary."""

    provider_event_id: str
    event_type: str
    occurred_at: datetime
    provider_message_id: str | None = None
    recipient_email: str | None = None
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of asking the provider what happened to an earlier request."""

    state: str
    provider_message_id: str | None = None
    detail: str | None = None

    @property
    def resolved(self) -> bool:
        return self.state not in {"unknown", "not_found"}


@dataclass(frozen=True)
class CapabilityDeclaration:
    """What an adapter can and cannot do, recorded next to the implementation."""

    supports_idempotency: bool
    #: Scope and lifetime of the provider's idempotency guarantee, verbatim from
    #: the adapter's documented behaviour.
    idempotency_scope: str = ""
    idempotency_retention_seconds: int | None = None
    webhook_signature_scheme: str = ""
    has_reconciliation_lookup: bool = False
    has_capacity_endpoint: bool = False
    documentation_ref: str = ""
    notes: str = ""


class ProviderAdapter(Protocol):
    """The common contract every adapter implements (SPEC.md section 6)."""

    name: str
    capabilities: CapabilityDeclaration

    async def verify_account(self, credential: Secret, account_ref: str) -> AccountVerification:
        """Confirm the account is reachable and report verified facts."""

    async def refresh_capacity(self, credential: Secret) -> CapacitySnapshot:
        """Return the freshest capacity facts the provider exposes."""

    async def send(
        self,
        credential: Secret,
        message: OutboundMessage,
        idempotency_key: str | None,
    ) -> SubmitResult:
        """Submit one message and normalize the outcome."""

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: Secret
    ) -> bool:
        """Verify a webhook signature over the raw body."""

    def normalize_webhook(self, body: bytes) -> list[NormalizedProviderEvent]:
        """Map a verified payload onto normalized events."""

    async def reconcile(
        self,
        credential: Secret,
        provider_message_id: str | None,
        idempotency_key: str,
    ) -> ReconciliationResult:
        """Resolve an ambiguous attempt without creating a duplicate send."""
