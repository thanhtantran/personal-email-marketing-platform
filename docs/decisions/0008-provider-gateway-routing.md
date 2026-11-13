# 0008. Provider gateway: compliant capacity routing

- Status: Accepted
- Date: 2026-11-13
- Related: [0006-first-provider-resend.md](0006-first-provider-resend.md),
  [0004-secret-encryption.md](0004-secret-encryption.md), SPEC.md sections 2, 5, 6

## Context

SPEC.md makes several sending guarantees that cannot be met by a naive "pick an API key and send"
path: marketing eligibility is a per-account capability with evidence, provider capacity is an
external dated fact that may be unknown, and an ambiguous submit must never be silently retried.
Stage 5 needs one place that decides *whether* and *where* a message may be sent and records *why*
it was held, so the API, scheduler and workers cannot diverge.

## Decision

- **The account is the quota boundary, never a credential.** Capacity, rate and routing are
  reserved on `provider_accounts`; adding or rotating a `provider_credentials` row never multiplies
  the account's quota (SPEC.md invariant 3). Credentials are AES-256-GCM envelopes and stay
  write-only (ADR 0004).
- **Eligibility and capacity are dated facts.** `eligibility_verified_at` and `quota_refreshed_at`
  make staleness observable; routing excludes an account whose facts are older than
  `PROVIDER_ELIGIBILITY_TTL_SECONDS` / `PROVIDER_CAPACITY_TTL_SECONDS`, or whose eligibility for the
  requested message class was never verified. A provider that reports no cap stays *unknown* —
  unknown blocks routing rather than defaulting to a guessed number (SPEC.md invariant 9).
- **Routing is deterministic, not random.** Eligible accounts are ranked by
  `(priority, -monthly_remaining, -daily_remaining, -weight, id)`, so the same state yields the same
  choice and failover is reproducible. Every excluded account contributes a *routing exclusion
  reason* the operator can read.
- **Ambiguity is never auto-resubmitted.** A submit timeout after the request left the app records
  the attempt as `unknown` **before** any further work; the recipient is only retried after
  reconciliation confirms non-acceptance, or when the adapter documents an idempotency guarantee
  that covers the retry window (Resend `Idempotency-Key`, 24h). Provider acceptance is recorded as
  acceptance, not delivery (SPEC.md section 5).
- **Provider policy/quota errors pause routing.** An account returning a policy or quota error is
  excluded and a send that cannot route is *deferred* (held and rescheduled by
  `PROVIDER_ROUTING_DEFER_SECONDS`), never dropped. The tenant-level marketing pause is durable
  operator state in PostgreSQL so it survives a restart and is visible to the owner.

## Consequences

- The dispatch worker is a thin loop: it reconciles unresolved recipients first, asks the gateway to
  submit one recipient at a time, and persists each attempt before the network call.
- Operator surfaces must expose account status, last verification/refresh time, known capacity and
  the current exclusion reasons; the `/provider-accounts` endpoints and the routing-status view do.
- Resend exposes no usage API, so capacity is refreshed from operator-recorded, provider-confirmed
  values and carries an observation timestamp.

## Alternatives considered

- **Round-robin across credentials for "more throughput".** Rejected: it would multiply an account's
  real provider-side quota and defeat the quota boundary.
- **Auto-retry an ambiguous submit.** Rejected: it risks duplicate sends because acceptance is not
  observable at that moment.
- **Derive quota from key count or a free-tier assumption.** Rejected: quota facts are external and
  must stay dated and verifiable.

## Revisit trigger

A provider exposes a trustworthy usage/quota API, the idempotency window changes, or marketing
eligibility rules or terms change for an enabled provider.
