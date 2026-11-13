"""Deterministic mock provider adapter.

This adapter exists to exercise campaign state and failure semantics before any
production send is enabled. It is **clearly labelled and incapable of sending a
real message**: it never opens a network connection and always reports
``name="mock"`` and ``enqueues_real_messages=False``
(IMPLEMENTATION_PLAN Stage 5). It is the adapter used by the contract tests and
by the simulated failure cases in the exit gate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.providers.contract import (
    AccountVerification,
    CapabilityDeclaration,
    CapacitySnapshot,
    MessageClass,
    NormalizedProviderEvent,
    OutboundMessage,
    ProviderTimeoutError,
    ReconciliationResult,
    Secret,
    SubmitOutcome,
    SubmitResult,
)

MOCK_PROVIDER_NAME = "mock"
SIGNATURE_HEADER = "x-mock-signature"


class MockProviderAdapter:
    """Scriptable stand-in for a real provider; never touches the network."""

    name = MOCK_PROVIDER_NAME
    is_mock = True
    enqueues_real_messages = False

    capabilities = CapabilityDeclaration(
        supports_idempotency=True,
        idempotency_scope="mock: per recipient idempotency key, unlimited retention",
        idempotency_retention_seconds=None,
        webhook_signature_scheme="hmac-sha256 over the raw body, header x-mock-signature",
        has_reconciliation_lookup=True,
        has_capacity_endpoint=True,
        documentation_ref="app/providers/mock.py",
        notes="Test double for contract and failure-path testing; sends nothing.",
    )

    def __init__(
        self,
        *,
        account_ref: str = "mock-account",
        valid: bool = True,
        health_state: str = "healthy",
        eligible_message_classes: Sequence[str] = (MessageClass.MARKETING.value,),
        sender_domains: Sequence[str] = ("example.com",),
        capacity: CapacitySnapshot | None = None,
        script: Sequence[SubmitResult | Exception] | None = None,
        default_result: SubmitResult | None = None,
        reconcile_state: str = "accepted",
    ) -> None:
        self.account_ref = account_ref
        self._valid = valid
        self._health_state = health_state
        self._eligible = frozenset(eligible_message_classes)
        self._sender_domains = list(sender_domains)
        self._capacity = capacity
        self._script = list(script or [])
        self._default_result = default_result or SubmitResult(
            outcome=SubmitOutcome.ACCEPTED, provider_message_id=f"mock_{uuid.uuid4().hex[:12]}"
        )
        self._reconcile_state = reconcile_state
        self.sent: list[OutboundMessage] = []

    # ------------------------------------------------------------- contract
    async def verify_account(self, credential: Secret, account_ref: str) -> AccountVerification:
        return AccountVerification(
            account_ref=account_ref or self.account_ref,
            valid=self._valid,
            health_state=self._health_state,
            eligible_message_classes=self._eligible,
            sender_domains=list(self._sender_domains),
            observed_by="mock",
            detail="mock adapter: no provider call was made",
        )

    async def refresh_capacity(self, credential: Secret) -> CapacitySnapshot:
        if self._capacity is not None:
            return self._capacity
        return CapacitySnapshot(
            observed_at=datetime.now(UTC),
            source="mock",
            daily_limit=None,
            monthly_limit=None,
            notes="mock adapter: capacity is unknown until an operator records it",
        )

    async def send(
        self,
        credential: Secret,
        message: OutboundMessage,
        idempotency_key: str | None,
    ) -> SubmitResult:
        self.sent.append(message)
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self._default_result

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: Secret
    ) -> bool:
        provided = _header(headers, SIGNATURE_HEADER)
        if not provided:
            return False
        expected = hmac.new(
            secret.reveal().encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    def normalize_webhook(self, body: bytes) -> list[NormalizedProviderEvent]:
        payload = json.loads(body.decode("utf-8"))
        data = payload.get("data", {})
        event_id = str(payload.get("id") or _digest(body))
        occurred = payload.get("created_at")
        return [
            NormalizedProviderEvent(
                provider_event_id=event_id,
                event_type=str(payload.get("type", "unknown")),
                occurred_at=_parse_time(occurred),
                provider_message_id=data.get("email_id"),
                recipient_email=data.get("to"),
                payload=payload,
            )
        ]

    async def reconcile(
        self,
        credential: Secret,
        provider_message_id: str | None,
        idempotency_key: str,
    ) -> ReconciliationResult:
        if provider_message_id is None and self._reconcile_state == "not_found":
            return ReconciliationResult(state="not_found", detail="mock: no matching send")
        return ReconciliationResult(
            state=self._reconcile_state,
            provider_message_id=provider_message_id,
            detail="mock adapter: state reported from scripted configuration",
        )


def timeout_result() -> ProviderTimeoutError:
    """Convenience factory for the ambiguous post-send case used in tests."""
    return ProviderTimeoutError("mock: no response after the request was sent")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:32]


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)
