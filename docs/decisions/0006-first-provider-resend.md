# 0006. First provider adapter (Resend)

- Status: Accepted
- Date: 2026-11-09
- Related: [provider-evaluation-resend.md](../provider-evaluation-resend.md), SPEC.md section 6

## Context

The provider adapter choice materially affects the sending design: marketing eligibility, quota
visibility, idempotency, reconciliation and webhook semantics. Stages 0-4 use a mock adapter; the
real adapter is implemented in Stage 5. A candidate must be verified against current official
documentation and the specific account's status before enablement.

## Decision

- First production adapter candidate: **Resend**.
- The evaluation (verified 2026-11-09) confirms marketing use (Broadcasts) is permitted under the
  AUP, `Idempotency-Key` support (24h), Svix-signed webhooks with `svix-id` dedupe, and
  `GET /emails/:id` reconciliation.
- **Quota is per provider-side team/account, not per API key or domain**, and the evaluation found
  **no public API to read current usage/quota**. Consequence: the operator must set conservative
  local caps and manually refresh account capacity from the provider dashboard; routing treats
  stale/unknown capacity as blocking.
- The adapter must map HTTP outcomes to `SubmitResult` per the evaluation's table, and must never
  assume a free-tier quota or permission.

## Consequences

- Stages 0-4 use the mock adapter; no production sends occur until Stage 5 passes its exit gate.
- A capacity-refresh path captures operator-entered, provider-confirmed values and a review date.
- Quota/pricing/permission facts are stored as external, dated account state — never hard-coded.

## Alternatives considered

- Amazon SES / SendGrid: kept as later candidates (P1 multiple adapters).
- Deciding the provider only at Stage 5: rejected — the sending design depends on it now.

## Revisit trigger

Provider terms/quota change, a provider notice, or the adapter failing its Stage 5 sandbox
contract tests.
