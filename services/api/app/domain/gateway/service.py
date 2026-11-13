"""Provider gateway: the only place campaign dispatch talks to a provider.

The per-recipient flow follows SPEC.md section 5 exactly:

1. revalidate consent and suppression for the recipient,
2. choose an eligible account, respecting a global marketing pause,
3. reserve the account's quota and check its account/domain rate gates,
4. persist a ``send_attempt`` row **before** the network call,
5. call the adapter, then classify and persist the outcome on both the attempt
   and the recipient ledger,

and it never resubmits an ambiguous request until reconciliation proves the
earlier request was not accepted (SPEC.md invariant 6). Nothing here invents a
quota: capacity comes from the account row, which holds provider-confirmed or
operator-recorded, dated facts (SPEC.md invariant 9).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    CampaignRecipient,
    ProviderAccount,
    ProviderCredential,
    SendAttempt,
)
from app.db.models.campaign import (
    RECIPIENT_STATUS_ACCEPTED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_RETRY,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNKNOWN,
)
from app.db.models.provider import (
    ATTEMPT_ACCEPTED,
    ATTEMPT_PERMANENT,
    ATTEMPT_TRANSIENT,
    ATTEMPT_UNKNOWN,
    MESSAGE_CLASS_MARKETING,
)
from app.domain.audience.consent import is_eligible
from app.domain.content.personalization import render, values_from_contact
from app.domain.events.unsubscribe import unsubscribe_headers
from app.domain.gateway import eligibility, routing
from app.domain.gateway.capacity import RateGate, capacity_from_account, reserve_capacity
from app.domain.gateway.retry import (
    RetryDecision,
    RetryPolicy,
    circuit_health_for,
    classify,
)
from app.observability.metrics import PROVIDER_SUBMISSIONS, PROVIDER_SUBMIT_SECONDS
from app.providers.contract import (
    HEALTH_HEALTHY,
    MessageClass,
    OutboundMessage,
    ProviderAdapter,
    ProviderAdapterError,
    Secret,
    SubmitOutcome,
    SubmitResult,
)
from app.providers.registry import get_adapter
from app.repositories.audit_repo import AuditRepository
from app.repositories.campaign_repo import CampaignRecipientRepository
from app.repositories.contact_repo import ContactRepository
from app.repositories.provider_repo import (
    ProviderAccountRepository,
    ProviderCredentialRepository,
    ProviderRoutingControlRepository,
)
from app.repositories.send_attempt_repo import SendAttemptRepository
from app.repositories.suppression_repo import SuppressionRepository
from app.security.encryption import EncryptionKeyError, get_secret_box_provider

#: Returned when routing is deliberately stopped; nothing is written for the
#: recipient, so the caller can stop the pass and resume later.
STATUS_HELD = "held"

#: Reconciliation states that prove the provider did accept the earlier request.
RECONCILED_ACCEPTED_STATES: frozenset[str] = frozenset(
    {
        "accepted",
        "delivered",
        "deferred",
        "bounced_hard",
        "bounced_soft",
        "complained",
        "opened",
        "clicked",
    }
)

#: Reconciliation states that prove the provider did *not* accept the request.
RECONCILED_NOT_ACCEPTED_STATES: frozenset[str] = frozenset({"rejected"})

RECIPIENT_SKIP_CONTACT_MISSING = "contact_missing"
RECIPIENT_SKIP_NOT_CONSENTED = "not_consented"
RECIPIENT_SKIP_SUPPRESSED = "suppressed"
RECIPIENT_SKIP_NO_ROUTE = "no_route"
HOLD_REASON_MARKETING_PAUSED = "marketing_paused"


@dataclass(frozen=True)
class GatewayStatus:
    """Operator-visible gateway state for one tenant and message class."""

    paused: bool
    pause_reason: str | None
    marketing_eligible: bool
    capacity_fresh: bool
    exclusions: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SubmissionReport:
    """The outcome of one recipient submission, as written to the ledger."""

    status: str
    account_id: uuid.UUID | None = None
    provider_message_id: str | None = None
    error_code: str | None = None
    next_attempt_at: datetime | None = None
    needs_reconcile: bool = False
    exclusions: list[dict] = field(default_factory=list)

    @property
    def held(self) -> bool:
        return self.status == STATUS_HELD


@dataclass(frozen=True)
class _Selection:
    account: ProviderAccount | None
    credential: ProviderCredential | None
    secret: Secret | None
    exclusions: list[routing.RoutingExclusion]
    paused: bool
    pause_reason: str | None


@dataclass(frozen=True)
class _RecipientCheck:
    contact: object | None
    reason: str | None


def build_outbound_message(
    content: dict,
    *,
    to_email: str,
    contact: object | None = None,
    headers: Mapping[str, str] | None = None,
) -> OutboundMessage:
    """Render the frozen snapshot content for one recipient.

    Personalization always comes from the frozen snapshot source, never from the
    live template, so a template edit cannot change an in-flight campaign.
    """
    values = values_from_contact(contact) if contact is not None else {}
    subject = render(str(content.get("subject") or ""), values, escape=False).body
    body_html = render(str(content.get("html") or ""), values, escape=True).body
    body_text = render(str(content.get("text_body") or ""), values, escape=False).body
    return OutboundMessage(
        message_class=MessageClass.MARKETING,
        to_email=to_email,
        from_email=str(content.get("from_email") or ""),
        from_name=str(content.get("from_name") or ""),
        subject=subject,
        html=body_html,
        text=body_text,
        reply_to=content.get("reply_to") or None,
        headers=headers or {},
    )


def _message_digest(message: OutboundMessage) -> str:
    payload = "\x1f".join(
        [message.to_email, message.from_email, message.subject, message.html, message.text]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _domain_of(email: str) -> str | None:
    _, _, domain = email.partition("@")
    return domain.lower().strip() or None


def _exclusions(items: list[routing.RoutingExclusion]) -> list[dict]:
    return [asdict(item) | {"account_id": str(item.account_id)} for item in items]


class ProviderGateway:
    """Campaign-dispatch side of the provider boundary."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        settings: Settings,
        *,
        redis: object | None = None,
        adapter_factory: Callable[[str], ProviderAdapter] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings
        self.accounts = ProviderAccountRepository(session, tenant_id)
        self.credentials = ProviderCredentialRepository(session, tenant_id)
        self.attempts = SendAttemptRepository(session, tenant_id)
        self.recipients = CampaignRecipientRepository(session, tenant_id)
        self.contacts = ContactRepository(session, tenant_id)
        self.suppressions = SuppressionRepository(session, tenant_id)
        self.controls = ProviderRoutingControlRepository(session, tenant_id)
        self.audit = AuditRepository(session, tenant_id)
        self.rate_gate = RateGate(redis)  # type: ignore[arg-type]
        self.policy = RetryPolicy(max_attempts=settings.send_max_attempts)
        self._adapter_factory = adapter_factory
        self._now = now

    # -------------------------------------------------------------- state
    @property
    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    def _ttls(self) -> tuple[int, int]:
        return (
            self.settings.provider_eligibility_ttl_seconds,
            self.settings.provider_capacity_ttl_seconds,
        )

    def _adapter_for(self, provider: str) -> ProviderAdapter:
        if self._adapter_factory is not None:
            return self._adapter_factory(provider)
        return get_adapter(provider, settings=self.settings)

    async def status(self, *, message_class: str = MESSAGE_CLASS_MARKETING) -> GatewayStatus:
        """Summarize eligibility, capacity freshness and exclusion reasons."""
        now = self.now
        eligibility_ttl, capacity_ttl = self._ttls()
        control = await self.controls.get()
        paused = bool(control is not None and control.marketing_paused)

        accounts = await self.accounts.list_marketing_candidates()
        decision = routing.select_account(
            accounts,
            message_class=message_class,
            now=now,
            eligibility_ttl_seconds=eligibility_ttl,
            capacity_ttl_seconds=capacity_ttl,
        )
        verified = [
            account
            for account in accounts
            if eligibility.marketing_verified(
                account, now=now, eligibility_ttl_seconds=eligibility_ttl
            )
        ]
        capacity_ok = any(
            eligibility.marketing_capacity_fresh(
                account, now=now, capacity_ttl_seconds=capacity_ttl
            )
            for account in verified
        )
        return GatewayStatus(
            paused=paused,
            pause_reason=control.paused_reason if control is not None else None,
            marketing_eligible=bool(verified) and not paused,
            capacity_fresh=capacity_ok and not paused,
            exclusions=decision.exclusion_reasons(),
        )

    async def routing_decision(
        self, *, message_class: str = MESSAGE_CLASS_MARKETING, from_domain: str | None = None
    ) -> routing.RoutingDecision:
        """The routing decision an operator can inspect, including exclusions."""
        control = await self.controls.get()
        if control is not None and control.marketing_paused:
            return routing.paused_decision(control.paused_reason)
        eligibility_ttl, capacity_ttl = self._ttls()
        accounts = await self.accounts.list_marketing_candidates()
        return routing.select_account(
            accounts,
            message_class=message_class,
            now=self.now,
            eligibility_ttl_seconds=eligibility_ttl,
            capacity_ttl_seconds=capacity_ttl,
            from_domain=from_domain,
        )

    # -------------------------------------------------------- revalidation
    async def check_recipient(self, normalized_email: str) -> _RecipientCheck:
        """Revalidate consent/suppression immediately before submission.

        Consent and suppression are authoritative and are re-read at send time,
        not trusted from the launch snapshot (SPEC.md invariants 5 and 8).
        """
        contact = await self.contacts.get_by_email(normalized_email)
        if contact is None:
            return _RecipientCheck(None, RECIPIENT_SKIP_CONTACT_MISSING)
        if not is_eligible(status=contact.status, consent_status=contact.consent_status):
            return _RecipientCheck(contact, RECIPIENT_SKIP_NOT_CONSENTED)
        if await self.suppressions.exists(normalized_email):
            return _RecipientCheck(contact, RECIPIENT_SKIP_SUPPRESSED)
        return _RecipientCheck(contact, None)

    # ------------------------------------------------------------ routing
    async def _select(
        self, *, message_class: str, from_domain: str | None, now: datetime
    ) -> _Selection:
        decision = await self.routing_decision(
            message_class=message_class, from_domain=from_domain
        )
        if decision.paused:
            return _Selection(None, None, None, [], True, decision.pause_reason)

        exclusions = list(decision.exclusions)
        for candidate in decision.ranked:
            credential = await self.credentials.get_active_for_account(candidate.id)
            if credential is None:
                exclusions.append(self._credential_exclusion(candidate))
                continue
            try:
                secret = self._reveal(credential)
            except EncryptionKeyError:
                exclusions.append(self._credential_exclusion(candidate))
                continue
            account = await self._reserve(candidate, now=now, from_domain=from_domain)
            if account is None:
                exclusions.append(
                    routing.RoutingExclusion(
                        candidate.id, candidate.provider, eligibility.EXCLUSION_QUOTA_EXHAUSTED
                    )
                )
                continue
            return _Selection(account, credential, secret, exclusions, False, None)
        return _Selection(None, None, None, exclusions, False, None)

    @staticmethod
    def _credential_exclusion(account: ProviderAccount) -> routing.RoutingExclusion:
        return routing.RoutingExclusion(
            account.id, account.provider, eligibility.EXCLUSION_CREDENTIAL
        )

    async def _reserve(
        self, candidate: ProviderAccount, *, now: datetime, from_domain: str | None
    ) -> ProviderAccount | None:
        """Lock the account and reserve one unit of its quota, or return ``None``."""
        locked = await self.accounts.get_for_update(candidate.id)
        if locked is None:
            return None
        facts = capacity_from_account(locked)
        allowed = await self.rate_gate.allow(
            scope="account", identifier=str(locked.id), per_second=facts.rate_per_second, now=now
        )
        if not allowed:
            return None
        if from_domain:
            domain_ok = await self.rate_gate.allow(
                scope="domain",
                identifier=from_domain,
                per_second=facts.domain_rate_per_second,
                now=now,
            )
            if not domain_ok:
                return None
        if not reserve_capacity(locked, now=now):
            return None
        return locked

    def _reveal(self, credential: ProviderCredential) -> Secret:
        box = get_secret_box_provider().box_for(credential.key_version)
        return Secret(box.decrypt(credential.secret_ciphertext), label=credential.label)

    # ----------------------------------------------------------- submission
    async def submit_recipient(
        self,
        recipient: CampaignRecipient,
        content: dict,
        *,
        message_class: str = MESSAGE_CLASS_MARKETING,
    ) -> SubmissionReport:
        """Submit one ledger recipient and persist the classified outcome."""
        now = self.now
        check = await self.check_recipient(recipient.email_snapshot)
        if check.reason is not None:
            await self.recipients.mark_skipped(recipient, error_code=check.reason, when=now)
            return SubmissionReport(status=RECIPIENT_STATUS_SKIPPED, error_code=check.reason)

        from_email = str(content.get("from_email") or "")
        selection = await self._select(
            message_class=message_class, from_domain=_domain_of(from_email), now=now
        )
        if selection.paused:
            return SubmissionReport(
                status=STATUS_HELD, error_code=HOLD_REASON_MARKETING_PAUSED, exclusions=[]
            )
        if selection.account is None or selection.secret is None:
            retry_at = now + timedelta(seconds=self.settings.provider_routing_defer_seconds)
            await self.recipients.mark_transient_retry(
                recipient,
                provider_account_id=None,
                error_code=RECIPIENT_SKIP_NO_ROUTE,
                next_attempt_at=retry_at,
            )
            return SubmissionReport(
                status=RECIPIENT_STATUS_RETRY,
                error_code=RECIPIENT_SKIP_NO_ROUTE,
                next_attempt_at=retry_at,
                exclusions=_exclusions(selection.exclusions),
            )

        account = selection.account
        headers: Mapping[str, str] = {}
        if message_class == MESSAGE_CLASS_MARKETING:
            headers = unsubscribe_headers(
                base_url=self.settings.api_base_url,
                secret=self.settings.session_key,
                tenant_id=self.tenant_id,
                recipient_id=recipient.id,
                campaign_id=recipient.campaign_id,
                contact_id=recipient.contact_id,
            )
        message = build_outbound_message(
            content,
            to_email=recipient.email_snapshot,
            contact=check.contact,
            headers=headers,
        )
        attempt_no = await self.attempts.next_attempt_no(recipient.id)
        attempt = await self.attempts.create_pending(
            recipient_id=recipient.id,
            provider_account_id=account.id,
            attempt_no=attempt_no,
            request_digest=_message_digest(message),
            idempotency_key=recipient.idempotency_key,
        )
        await self.session.flush()

        result = await self._send(account, selection.secret, message, recipient.idempotency_key)
        return await self._record(
            recipient, account, attempt, result, attempt_no=attempt_no, now=now
        )

    async def _send(
        self,
        account: ProviderAccount,
        secret: Secret,
        message: OutboundMessage,
        idempotency_key: str,
    ) -> SubmitResult:
        """Call the adapter, mapping a lost response to an ambiguous outcome."""
        adapter = self._adapter_for(account.provider)
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                adapter.send(secret, message, idempotency_key),
                timeout=self.settings.send_request_timeout_seconds,
            )
        except TimeoutError:
            return SubmitResult(outcome=SubmitOutcome.AMBIGUOUS, error_class="timeout")
        except ProviderAdapterError as exc:
            return SubmitResult(outcome=SubmitOutcome.AMBIGUOUS, error_class=type(exc).__name__)
        finally:
            PROVIDER_SUBMIT_SECONDS.observe(
                time.perf_counter() - started, provider=account.provider
            )

    async def _record(
        self,
        recipient: CampaignRecipient,
        account: ProviderAccount,
        attempt: SendAttempt,
        result: SubmitResult,
        *,
        attempt_no: int,
        now: datetime,
    ) -> SubmissionReport:
        decision = classify(result, attempt_no=attempt_no, policy=self.policy)
        PROVIDER_SUBMISSIONS.inc(provider=account.provider, outcome=result.outcome.value)

        if result.outcome is SubmitOutcome.ACCEPTED:
            await self.attempts.record_result(
                attempt,
                state=ATTEMPT_ACCEPTED,
                when=now,
                provider_message_id=result.provider_message_id,
                response_code=result.response_code,
            )
            await self.recipients.mark_accepted(
                recipient,
                provider_account_id=account.id,
                provider_message_id=result.provider_message_id,
                when=now,
            )
            await self._settle_health(account, HEALTH_HEALTHY, now=now, reason=None)
            return SubmissionReport(
                status=RECIPIENT_STATUS_ACCEPTED,
                account_id=account.id,
                provider_message_id=result.provider_message_id,
            )

        if decision.needs_reconcile:
            # Ambiguous: never auto-resubmit; reconciliation must first confirm the
            # earlier request was not accepted.
            await self.attempts.record_result(
                attempt,
                state=ATTEMPT_UNKNOWN,
                when=now,
                error_class=result.error_class,
                response_code=result.response_code,
                unknown_reason=result.error_class or "ambiguous",
            )
            await self.recipients.mark_unknown(
                recipient,
                provider_account_id=account.id,
                error_code=result.error_class,
                when=now,
            )
            return SubmissionReport(
                status=RECIPIENT_STATUS_UNKNOWN,
                account_id=account.id,
                error_code=result.error_class,
                needs_reconcile=True,
            )

        if decision.retry:
            retry_at = now + timedelta(seconds=decision.delay_seconds or 0)
            await self.attempts.record_result(
                attempt,
                state=ATTEMPT_TRANSIENT,
                when=now,
                error_class=result.error_class,
                response_code=result.response_code,
            )
            await self.recipients.mark_transient_retry(
                recipient,
                provider_account_id=account.id,
                error_code=result.error_class,
                next_attempt_at=retry_at,
            )
            await self._hold_routing(account, decision, now=now)
            return SubmissionReport(
                status=RECIPIENT_STATUS_RETRY,
                account_id=account.id,
                error_code=result.error_class,
                next_attempt_at=retry_at,
            )

        # Definitive permanent rejection, or a transient rejection past the cap.
        terminal_state = (
            ATTEMPT_PERMANENT
            if result.outcome is SubmitOutcome.DEFINITIVE_PERMANENT_REJECTION
            else ATTEMPT_TRANSIENT
        )
        await self.attempts.record_result(
            attempt,
            state=terminal_state,
            when=now,
            error_class=result.error_class,
            response_code=result.response_code,
        )
        await self.recipients.mark_permanent_failure(
            recipient,
            provider_account_id=account.id,
            error_code=result.error_class,
            when=now,
        )
        await self._hold_routing(account, decision, now=now)
        return SubmissionReport(
            status=RECIPIENT_STATUS_FAILED,
            account_id=account.id,
            error_code=result.error_class,
        )

    # ------------------------------------------------------------ reconcile
    async def reconcile_recipient(self, recipient: CampaignRecipient) -> SubmissionReport:
        """Resolve an ambiguous attempt before any further submission is allowed."""
        now = self.now
        attempt = await self.attempts.latest_for_recipient(recipient.id)
        if attempt is None or attempt.state != ATTEMPT_UNKNOWN:
            return SubmissionReport(status=recipient.status, error_code=recipient.error_code)
        account = await self.accounts.get(attempt.provider_account_id)
        credential = await self.credentials.get(attempt.provider_account_id)
        if account is None or credential is None:
            return SubmissionReport(
                status=RECIPIENT_STATUS_UNKNOWN,
                error_code=recipient.error_code,
                needs_reconcile=True,
            )
        try:
            secret = self._reveal(credential)
        except EncryptionKeyError:
            return SubmissionReport(
                status=RECIPIENT_STATUS_UNKNOWN,
                error_code=recipient.error_code,
                needs_reconcile=True,
            )
        result = await self._adapter_for(account.provider).reconcile(
            secret, attempt.provider_message_id, attempt.idempotency_key
        )

        if result.state in RECONCILED_ACCEPTED_STATES:
            provider_message_id = result.provider_message_id or attempt.provider_message_id
            await self.attempts.record_result(
                attempt, state=ATTEMPT_ACCEPTED, when=now, provider_message_id=provider_message_id
            )
            await self.recipients.mark_accepted(
                recipient,
                provider_account_id=account.id,
                provider_message_id=provider_message_id,
                when=now,
            )
            return SubmissionReport(
                status=RECIPIENT_STATUS_ACCEPTED,
                account_id=account.id,
                provider_message_id=provider_message_id,
            )

        if result.state in RECONCILED_NOT_ACCEPTED_STATES:
            # Confirmed non-acceptance: a retry can no longer duplicate a send.
            retry_at = now + timedelta(
                seconds=self.policy.backoff(attempt.attempt_no, jitter_key="reconciled")
            )
            await self.attempts.record_result(
                attempt, state=ATTEMPT_TRANSIENT, when=now, error_class="reconciled_not_accepted"
            )
            await self.recipients.mark_transient_retry(
                recipient,
                provider_account_id=account.id,
                error_code="reconciled_not_accepted",
                next_attempt_at=retry_at,
            )
            return SubmissionReport(
                status=RECIPIENT_STATUS_RETRY,
                account_id=account.id,
                error_code="reconciled_not_accepted",
                next_attempt_at=retry_at,
            )

        # Still unresolved: stay ``unknown`` with no retry scheduled.
        return SubmissionReport(
            status=RECIPIENT_STATUS_UNKNOWN,
            account_id=account.id,
            error_code=recipient.error_code,
            needs_reconcile=True,
        )

    # --------------------------------------------------------------- health
    async def _hold_routing(
        self, account: ProviderAccount, decision: RetryDecision, *, now: datetime
    ) -> None:
        target = circuit_health_for(decision.reason)
        if target is None:
            return
        await self._settle_health(account, target, now=now, reason=decision.reason)

    async def _settle_health(
        self, account: ProviderAccount, health_state: str, *, now: datetime, reason: str | None
    ) -> None:
        if account.health_state == health_state:
            return
        previous = account.health_state
        await self.accounts.update_fields(account, {"health_state": health_state})
        await self.audit.record(
            action="provider.account_health_changed",
            object_type="provider_account",
            object_id=str(account.id),
            details={
                "provider": account.provider,
                "from": previous,
                "to": health_state,
                "reason": reason,
                "at": now.isoformat(),
            },
        )
