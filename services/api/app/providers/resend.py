"""Resend adapter (first production candidate; see docs/decisions/0006).

The HTTP-outcome mapping follows the verified provider evaluation
(docs/provider-evaluation-resend.md). No quota, price or permission is
hard-coded: quota values are read from provider response headers when present and
are otherwise reported as unknown, because Resend publishes no usage API and
capacity remains an operator-recorded, dated fact.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from app.providers.contract import (
    HEALTH_HEALTHY,
    HEALTH_UNKNOWN,
    AccountVerification,
    CapabilityDeclaration,
    CapacitySnapshot,
    NormalizedProviderEvent,
    OutboundMessage,
    ProviderTimeoutError,
    ReconciliationResult,
    Secret,
    SubmitOutcome,
    SubmitResult,
)

RESEND_PROVIDER_NAME = "resend"
RESEND_BASE_URL = "https://api.resend.com"
USER_AGENT = "personal-email-platform/0.1 (+provider-gateway-stage5)"

#: Svix tolerates a small clock skew; a replayed older delivery is rejected.
DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300
SVIX_SECRET_PREFIX = "whsec_"

#: Provider event names mapped onto the platform's normalized vocabulary
#: (SPEC.md section 7). The raw name is preserved in the event payload.
_EVENT_TYPES: dict[str, str] = {
    "email.sent": "submitted",
    "email.delivered": "delivered",
    "email.delivery_delayed": "deferred",
    "email.complained": "complained",
    "email.bounced": "bounced",
    "email.failed": "rejected",
    "email.opened": "opened",
    "email.clicked": "clicked",
    "email.received": "received",
}

_LAST_EVENT_STATES: dict[str, str] = {
    "sent": "accepted",
    "delivered": "delivered",
    "delivery_delayed": "deferred",
    "bounced": "bounced_hard",
    "complained": "complained",
    "failed": "rejected",
    "opened": "opened",
    "clicked": "clicked",
}


class ResendProviderAdapter:
    """Resend adapter implementing the common contract."""

    name = RESEND_PROVIDER_NAME
    is_mock = False
    enqueues_real_messages = True

    capabilities = CapabilityDeclaration(
        supports_idempotency=True,
        idempotency_scope="POST /emails and /emails/batch, keyed per request for 24 hours",
        idempotency_retention_seconds=86_400,
        webhook_signature_scheme="svix: hmac-sha256 over '{svix-id}.{svix-timestamp}.{body}'",
        has_reconciliation_lookup=True,
        has_capacity_endpoint=False,
        documentation_ref="docs/provider-evaluation-resend.md",
        notes=(
            "No public usage/quota API: capacity is operator-recorded and dated; "
            "quota is per provider team/account, never per API key."
        ),
    )

    def __init__(
        self,
        *,
        base_url: str = RESEND_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        signature_tolerance_seconds: int = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds
        self._tolerance = signature_tolerance_seconds

    # ------------------------------------------------------------- contract
    async def verify_account(self, credential: Secret, account_ref: str) -> AccountVerification:
        """Confirm the key works and report verified sender domains.

        Contractual marketing permission is **not** decided here: the adapter
        reports observable facts only, and an operator records the approved
        message classes with evidence and a verification date.
        """
        try:
            response = await self._request("GET", "/domains", credential)
        except ProviderTimeoutError:
            return AccountVerification(
                account_ref=account_ref,
                valid=False,
                health_state=HEALTH_UNKNOWN,
                eligible_message_classes=frozenset(),
                observed_by="adapter",
                detail="timeout while verifying the account; state is unknown",
            )
        if response.status_code >= 400:
            return AccountVerification(
                account_ref=account_ref,
                valid=False,
                health_state="unhealthy",
                eligible_message_classes=frozenset(),
                observed_by="adapter",
                detail=f"verification failed with HTTP {response.status_code}",
            )
        payload = _json(response) or {}
        domains = [
            str(item.get("name"))
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("status") == "verified" and item.get("name")
        ]
        return AccountVerification(
            account_ref=account_ref,
            valid=bool(domains),
            health_state=HEALTH_HEALTHY,
            # The adapter cannot decide contractual eligibility, so it reports no
            # approved classes; operator approval is required and stored on the
            # account row.
            eligible_message_classes=frozenset(),
            sender_domains=domains,
            observed_by="adapter",
            detail=None if domains else "no verified sender domain was reported",
        )

    async def refresh_capacity(self, credential: Secret) -> CapacitySnapshot:
        """Probe the account and read whatever capacity headers the provider sends.

        Resend exposes no usage API, so a missing header yields ``None``
        (unknown) rather than an inferred number; routing treats unknown as
        blocking until an operator records provider-confirmed capacity.
        """
        observed_at = datetime.now(UTC)
        try:
            response = await self._request("GET", "/domains", credential)
        except ProviderTimeoutError:
            return CapacitySnapshot(
                observed_at=observed_at,
                source="resend:unknown",
                notes="timeout while probing capacity; values are unknown",
            )
        return CapacitySnapshot(
            observed_at=observed_at,
            source="resend:response-headers",
            daily_limit=_int_header(response.headers, "x-resend-daily-quota"),
            daily_used=None,
            monthly_limit=_int_header(response.headers, "x-resend-monthly-quota"),
            monthly_used=None,
            rate_per_second=_int_header(response.headers, "ratelimit-limit"),
            notes="provider publishes no usage API; operator-recorded caps stay authoritative",
        )

    async def send(
        self,
        credential: Secret,
        message: OutboundMessage,
        idempotency_key: str | None,
    ) -> SubmitResult:
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body: dict[str, object] = {
            "from": _format_from(message),
            "to": [message.to_email],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        if message.reply_to:
            body["reply_to"] = message.reply_to
        if message.headers:
            body["headers"] = dict(message.headers)
        try:
            response = await self._request(
                "POST", "/emails", credential, json_body=body, headers=headers
            )
        except ProviderTimeoutError as exc:
            # The request may have reached the provider: the caller must record
            # the attempt as unknown and reconcile before any retry.
            raise ProviderTimeoutError(str(exc)) from exc
        return _classify_send(response)

    def verify_webhook(
        self, headers: Mapping[str, str], body: bytes, secret: Secret
    ) -> bool:
        message_id = _header(headers, "svix-id")
        timestamp = _header(headers, "svix-timestamp")
        signatures = _header(headers, "svix-signature")
        if not message_id or not timestamp or not signatures:
            return False
        try:
            sent_at = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - sent_at) > self._tolerance:
            return False
        signed = f"{message_id}.{timestamp}.".encode("ascii") + body
        raw_secret = secret.reveal()
        if raw_secret.startswith(SVIX_SECRET_PREFIX):
            raw_secret = raw_secret[len(SVIX_SECRET_PREFIX) :]
        try:
            key = base64.b64decode(raw_secret, validate=True)
        except (ValueError, binascii.Error):
            return False
        expected = base64.b64encode(
            hmac.new(key, signed, hashlib.sha256).digest()
        ).decode("ascii")
        for part in signatures.split():
            _, _, candidate = part.partition(",")
            if candidate and hmac.compare_digest(expected, candidate):
                return True
        return False

    def normalize_webhook(self, body: bytes) -> list[NormalizedProviderEvent]:
        payload = json.loads(body.decode("utf-8"))
        event_type = str(payload.get("type", ""))
        data = payload.get("data", {})
        if not isinstance(data, dict):
            data = {}
        bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
        normalized = _EVENT_TYPES.get(event_type, "unknown")
        if normalized == "bounced" and str(bounce.get("type", "")).lower() == "transient":
            normalized = "bounced_soft"
        elif normalized == "bounced":
            normalized = "bounced_hard"
        event_id = str(payload.get("id") or "") or _digest(body)
        return [
            NormalizedProviderEvent(
                provider_event_id=event_id,
                event_type=normalized,
                occurred_at=_parse_time(payload.get("created_at")),
                provider_message_id=data.get("email_id"),
                recipient_email=_first_recipient(data),
                payload=payload,
            )
        ]

    async def reconcile(
        self,
        credential: Secret,
        provider_message_id: str | None,
        idempotency_key: str,
    ) -> ReconciliationResult:
        """Resolve an ambiguous attempt by provider lookup.

        Without a provider message id there is nothing to look up, so the result
        stays unresolved: the worker must not resubmit an ambiguous request
        (SPEC.md section 5).
        """
        if not provider_message_id:
            return ReconciliationResult(
                state="not_found",
                detail="no provider message id to reconcile; idempotency key retained",
            )
        try:
            response = await self._request("GET", f"/emails/{provider_message_id}", credential)
        except ProviderTimeoutError:
            return ReconciliationResult(state="unknown", detail="timeout during reconciliation")
        if response.status_code == 404:
            return ReconciliationResult(
                state="not_found",
                provider_message_id=provider_message_id,
                detail="provider does not know this message id",
            )
        if response.status_code >= 400:
            return ReconciliationResult(
                state="unknown",
                provider_message_id=provider_message_id,
                detail=f"reconciliation failed with HTTP {response.status_code}",
            )
        payload = _json(response) or {}
        last_event = str(payload.get("last_event", ""))
        return ReconciliationResult(
            state=_LAST_EVENT_STATES.get(last_event, "accepted" if last_event else "unknown"),
            provider_message_id=provider_message_id,
            detail=f"provider last_event={last_event or 'unknown'}",
        )

    # --------------------------------------------------------------- helpers
    async def _request(
        self,
        method: str,
        path: str,
        credential: Secret,
        *,
        json_body: dict | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = {
            "Authorization": f"Bearer {credential.reveal()}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
        try:
            return await client.request(
                method,
                f"{self._base_url}{path}",
                json=json_body,
                headers=request_headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderTimeoutError(f"{method} {path} did not complete") from exc
        finally:
            if owns_client:
                await client.aclose()


def _classify_send(response: httpx.Response) -> SubmitResult:
    """Map a Resend response onto ``SubmitResult`` (evaluation mapping table)."""
    code = response.status_code
    payload = _json(response) or {}
    error_code = str(payload.get("name") or payload.get("type") or payload.get("error") or "")
    retry_after = _retry_after(response)
    detail = payload.get("message") if isinstance(payload.get("message"), str) else None

    if code in {200, 201, 202}:
        return SubmitResult(
            outcome=SubmitOutcome.ACCEPTED,
            provider_message_id=payload.get("id"),
            response_code=code,
        )

    if code in {400, 422}:
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION,
            error_class="validation",
            response_code=code,
            detail=detail or error_code or "invalid request",
        )

    if code == 401:
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION,
            error_class="auth",
            response_code=code,
            detail=detail or "credential rejected",
        )

    if code == 403:
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION,
            error_class="policy",
            response_code=code,
            detail=detail or error_code or "provider policy or configuration rejection",
        )

    if code == 409:
        if error_code in {"concurrent_idempotent_requests", "resource_locked"}:
            return SubmitResult(
                outcome=SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION,
                error_class="concurrency",
                response_code=code,
                retry_after_seconds=retry_after,
                detail=detail,
            )
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION,
            error_class="idempotency_conflict",
            response_code=code,
            detail=detail or "idempotency key reused with a different body",
        )

    if code == 429:
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION,
            error_class=_throttle_class(error_code),
            response_code=code,
            retry_after_seconds=retry_after,
            detail=detail or error_code or "provider rate or quota limit reached",
        )

    if code >= 500:
        return SubmitResult(
            outcome=SubmitOutcome.DEFINITIVE_TRANSIENT_REJECTION,
            error_class="server_error",
            response_code=code,
            retry_after_seconds=retry_after,
            detail=detail,
        )

    return SubmitResult(
        outcome=SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION,
        error_class="unexpected",
        response_code=code,
        detail=detail or error_code,
    )


def _throttle_class(error_code: str) -> str:
    lowered = error_code.lower()
    if "daily" in lowered:
        return "quota_daily"
    if "monthly" in lowered:
        return "quota_monthly"
    if "quota" in lowered:
        return "quota"
    return "rate_limit"


def _retry_after(response: httpx.Response) -> int | None:
    for name in ("retry-after", "ratelimit-reset"):
        value = _int_header(response.headers, name)
        if value is not None:
            return value
    return None


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = _header(headers, name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _json(response: httpx.Response) -> dict | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _format_from(message: OutboundMessage) -> str:
    if message.from_name:
        return f"{message.from_name} <{message.from_email}>"
    return message.from_email


def _first_recipient(data: Mapping[str, object]) -> str | None:
    to = data.get("to")
    if isinstance(to, str):
        return to
    if isinstance(to, list) and to:
        first = to[0]
        return first if isinstance(first, str) else None
    return None


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:32]


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_SIGNATURE_TOLERANCE_SECONDS",
    "RESEND_BASE_URL",
    "RESEND_PROVIDER_NAME",
    "ResendProviderAdapter",
]
