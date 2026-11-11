# Implementation Plan

**Product:** Personal Email Marketing Platform  
**Status:** Delivery plan  
**Version:** 1.0  
**Companion documents:** [PRD.md](PRD.md) · [SPEC.md](SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## 1. Delivery approach

Deliver a usable, single-owner application first, while preserving tenant ownership, provider-account boundaries, and event/state invariants from the first migration. Build a modular monolith with independently run API, worker, and scheduler processes. Complete each phase with a deployable increment and its operational notes.

### Phase 1 outcome

One owner can authenticate with Google, import and manage consent-based contacts, create reusable templates, prepare and schedule campaigns, route marketing email through explicitly eligible provider accounts, handle unsubscribes and provider events, and understand accepted, delivered, failed, and uncertain outcomes.

### Phase 2 outcome

Multiple isolated tenants can onboard and manage users, provider accounts, quotas, data, and billing with abuse controls and operational support processes. Phase 2 is not a prerequisite for launching the personal deployment.

## 2. Workstreams and sequencing

The sequence below is dependency-aware. Parallel work within a phase is appropriate after the contracts and schemas are agreed. Provider selection is an early decision because marketing eligibility, quota visibility, idempotency, reconciliation, and webhook support materially affect the sending design.

### Stage 0 — Decisions and project foundation

**Tasks**

- Create the repository structure in [ARCHITECTURE.md](ARCHITECTURE.md), CI checks, dependency lockfiles, local configuration example, and development setup guide.
- Record initial architecture decisions: frontend/API authentication model, migration tool, object storage implementation, secret encryption strategy, deployment target, and first provider candidate.
- Verify the candidate provider’s current official marketing-email permissions, account-level eligibility, quota visibility, rate limits, sender-domain requirements, idempotency and reconciliation options, webhook signatures/events, and applicable regional constraints.
- Define provisional deployment limits: import size/rows, batch sizes, request timeouts, retry bounds, log retention, and backup objectives. Clearly mark unverified values as operator settings.
- Establish threat model and data classification for contact information, credentials, consent evidence, and provider payloads.

**Exit gate**

- All implementation decisions that block foundational modules are documented.
- The selected provider is suitable for the intended marketing use based on current official documentation and the specific account’s status. If not, evaluate another candidate before gateway implementation.
- No provider quota or free-tier assumption is hard-coded as a product guarantee.

### Stage 1 — Runtime, persistence, and identity

**Tasks**

- Set up Docker Compose services for Next.js, FastAPI, PostgreSQL, Redis, Celery worker, single-active scheduler, migration job, and local S3-compatible storage as needed.
- Implement settings validation, secret injection, health/readiness endpoints, structured request IDs, and safe logging defaults.
- Create initial Alembic schema for users, tenants, memberships, sessions, and audit log. Seed a single tenant and bind the configured owner identity.
- Implement Google OIDC login/callback, state/nonce validation, session cookies, logout/revocation, and strict owner allowlist behavior.
- Add tenant-scoped repository/service patterns and composite tenant-aware constraints before adding audience tables.

**Exit gate**

- Local stack starts from documented steps and reports unhealthy dependencies accurately.
- Only the configured owner can authenticate into the workspace; non-owner identity is rejected.
- Every protected endpoint resolves tenant context from server-side membership and denies missing context.
- Database migration and rollback/recovery procedure is documented.

### Stage 2 — Audience, imports, consent, and suppression

**Tasks**

- Implement contact, tag, segment, suppression, import, and import-row schema and APIs.
- Build private object upload flow with constrained signed URLs, digest verification, size limits, and staging retention.
- Add CSV mapping, preview, normalization, validation, duplicate detection, row-level error codes, explicit merge behavior, and resumable idempotent commit.
- Implement tags and a validated segment AST with estimates. Reject arbitrary SQL or unsupported operators.
- Implement consent/source evidence fields, unsubscribe and suppression policy services, and audit events.
- Add safe CSV export escaping and contact export/deletion policy hooks.

**Exit gate**

- Replaying import commit does not duplicate rows or reapply unintended field merges.
- Import preview reports actionable accepted/duplicate/invalid/missing-consent totals.
- A suppressed or unsubscribed contact is excluded from eligible segment estimates and cannot be unsuppressed by duplicate import.
- Tenant boundaries and composite references are verified across contact/tag/segment operations.

### Stage 3 — Content and templates

**Tasks**

- Integrate GrapesJS into the Next.js editor and define supported components, MJML export, and saved editor-state format.
- Implement server-side MJML rendering, text alternative generation, preview rendering, and allowlist sanitizer.
- Add safe personalization variables, escaping, fallback values, and preflight missing-field report.
- Implement template versioning and controlled test sends via the provider gateway once available; until then use a deterministic preview/mock sender.
- Add responsive preview and an isolated preview origin/configuration where supported.

**Exit gate**

- A saved template can be reopened and rendered reproducibly from its versioned source.
- Generated output contains no scripts, event handlers, unsafe URL protocols, or disallowed embeds.
- Personalization cannot inject HTML through contact data; fallback behavior is visible in preview.
- Test-send action is restricted to verified addresses and does not enqueue a production campaign.

### Stage 4 — Campaign model, snapshots, and scheduling

**Tasks**

- Implement campaign lifecycle, state-transition service, campaign snapshots, recipient ledger, and idempotency keys.
- Add launch validation for content, sender identity, segment estimate, contact consent, suppressions, provider eligibility, and capacity freshness.
- Implement UTC scheduling with original timezone metadata and explicit daylight-saving ambiguous-time handling.
- Implement transactional outbox and idempotent Celery publisher/consumer. Add scheduler locking/lease and due-campaign claiming.
- Add pause, resume, and cancel behavior checked before every recipient submission.

**Exit gate**

- Launch freezes content and recipient snapshot; subsequent contact/template edits do not silently mutate in-flight recipients/content.
- Duplicate API requests or Celery delivery do not create duplicate recipients or launch work.
- Pause/cancel prevents future submissions and accurately preserves already accepted messages.
- Scheduler restart does not lose or double-run due campaigns.

### Stage 5 — Provider gateway and compliant capacity routing

**Tasks**

- Implement provider account and credential models separately; encrypt credential values and expose write-only secret management.
- Implement adapter contract, capability declarations, account verification, sender-domain configuration, capacity refresh, submit results, webhook verification, and reconciliation.
- Store account eligibility for `marketing` or `transactional` separately. Block marketing sends when eligibility is absent, stale, or not approved for intended use.
- Implement quota reservation, account-level rate limiting, per-domain limits, routing policy, circuit breaker, and account/global pause controls.
- Implement classified retry behavior. Persist send attempts before network calls. Record ambiguous post-send timeouts as `unknown`; reconcile before any retry.
- Add operator-visible account status, last verification/refresh time, known capacity, routing exclusion reason, and audit log.

**Exit gate**

- Adapter passes the common contract against provider sandbox/test environment and simulated failure cases.
- Account-level quota is not multiplied by adding API keys.
- Transactional-only, ineligible, unhealthy, stale-capacity, or over-limit accounts cannot receive marketing traffic.
- No ambiguous request is automatically resubmitted through the same or another account without confirmed non-acceptance or documented provider idempotency guarantee.
- A provider policy/quota error stops or holds routing and is visible to the owner.

### Stage 6 — Webhooks, unsubscribe, and analytics

**Tasks**

- Implement signed unsubscribe tokens and one-click unsubscribe endpoint. Add immediate suppression updates.
- Implement provider webhook routes, signature/timestamp checks, durable event acceptance, replay dedupe, payload retention, and asynchronous normalization.
- Build normalized recipient event reducer resilient to duplicate and out-of-order events; allow authoritative event to resolve unknown status.
- Add campaign analytics for queued, accepted, provider-reported delivered, bounced, complained, unsubscribed, failed, and unknown.
- If tracking is enabled, add configurable first-party click/open tracking, privacy disclosure, and clear metric caveats.

**Exit gate**

- Replayed or forged webhooks do not affect campaign analytics or suppression state.
- Complaint, hard bounce, and unsubscribe create idempotent suppression records.
- One-click unsubscribe takes effect before the next dispatch eligibility check.
- Dashboard labels provider acceptance separately from provider-reported delivery and distinguishes unknown outcomes.

### Stage 7 — Security hardening, operations, and release

**Tasks**

- Complete authorization, CSRF, XSS, SSRF, file validation, CSV formula injection, OAuth, webhook replay, and secret-redaction review.
- Add queue/provider/storage/database metrics, tracing, dashboards, alert thresholds, and operator runbooks.
- Implement encrypted backups, backup monitoring, restore drill, data retention jobs, and incident response basics.
- Add global campaign pause and per-account disablement controls; document provider-account credential rotation.
- Run the test strategy in [SPEC.md](SPEC.md), including fault injection for ambiguous submit outcomes, worker crashes, out-of-order webhooks, stale quotas, and cancellation races.
- Prepare deployment guide, DNS/sender verification checklist based on current provider documentation, and upgrade/migration notes.

**Exit gate**

- Release gates in [SPEC.md](SPEC.md) are met and recorded.
- Backup restore has been demonstrated in an isolated environment.
- No unresolved critical/high security findings; operational owner can pause sending and diagnose provider issues.
- Documentation clearly assigns provider terms, account eligibility, consent lawfulness, sender configuration, and retention responsibilities.

## 3. Phase 2 SaaS work plan

Begin after Phase 1 has stable isolation and operator runbooks.

1. Expand owner authorization to tenant membership, invitations, roles, account recovery, and audit workflows.
2. Build tenant onboarding and provisioning, per-tenant contact/send/storage limits, and usage metering.
3. Implement subscription billing and payment state only after plan definitions and support/refund processes are specified.
4. Add abuse prevention, complaint/bounce response, tenant risk review, global kill switch, and provider escalation process.
5. Add tenant export/deletion, data retention SLAs, support access approval/audit, and privacy request operations.
6. Add PostgreSQL RLS as defense in depth, verify connection pool tenant context reset, and test isolation under worker/webhook paths.
7. Scale workers and event storage using measured usage; introduce partitions or service separation only when justified by observed constraints.
8. Reassess encryption key ownership, data residency, per-tenant secret boundaries, disaster recovery, and availability targets.

**Phase 2 launch gate:** no public tenant signup until tenant isolation, abuse controls, billing/support processes, data handling, capacity policy, and incident response are operational and reviewed.

## 4. Cross-cutting definition of done

Every work item is complete only when:

- API and UI behavior match the documented contract and state transitions.
- Authorization and `tenant_id` context are enforced through API, worker, webhook, and scheduled paths.
- Idempotency and failure behavior are defined for any operation that can be retried.
- Consent, suppression, provider eligibility, and uncertain-delivery invariants remain intact.
- Migrations, configuration, logs/metrics, operator controls, and documentation are updated.
- Automated tests cover relevant success, boundary, and failure cases; no claim of execution is made until actually run and recorded.

## 5. Suggested initial backlog slices

1. Repository skeleton, Compose stack, configuration checks, and CI.
2. Tenant/user/session migrations and Google owner-only authentication.
3. Contacts, consent/suppressions, CSV preview, and idempotent import commit.
4. Tags and safe segment AST/query implementation.
5. Template editor, MJML render/sanitize, and preview.
6. Campaign CRUD, lifecycle, snapshot, and schedule model.
7. Outbox, worker ledger, pause/cancel, and mock provider adapter.
8. Provider review decision and first compliant adapter.
9. Account capacity reservation, rate controls, ambiguous outcome reconciliation.
10. Unsubscribe, webhooks, event reducer, and analytics.
11. Security review, backup/restore drill, monitoring, release packaging.

The mock adapter should be used to validate campaign state and failure semantics before production sends are enabled. It must be clearly labeled and incapable of sending real messages.

## 6. Delivery risks and contingency

| Risk | Contingency |
|---|---|
| Candidate provider does not allow the intended marketing use | Do not build a workaround. Choose an eligible provider or defer production sending. |
| Provider lacks reliable quota query or idempotent reconciliation | Use conservative operator-set caps and hold ambiguous attempts for reconciliation/manual resolution. |
| GrapesJS/MJML output compatibility is incomplete | Limit supported components, retain source and rendered snapshot, and validate test renders before campaign launch. |
| Contact count exceeds current database/storage capacity | Monitor growth, tune indexes/retention, scale infrastructure, then plan measured partitioning. No application-level unlimited-capacity promise. |
| Deliverability degrades | Pause provider/account/campaign, investigate list source and complaint/bounce signals, and follow provider guidance. Do not distribute load to evade review. |
| Phase 2 isolation requires incompatible changes | Phase 1 keeps tenant IDs, composite keys, tenant-scoped repositories, and tenant-bearing job envelopes from initial migrations. |

## 7. Change control

When an implementation decision changes a user-visible requirement or safety invariant, update the affected section in [PRD.md](PRD.md), [SPEC.md](SPEC.md), and/or [ARCHITECTURE.md](ARCHITECTURE.md) in the same change. Record consequential tradeoffs in `docs/decisions/` with context, decision, alternatives, and revisit trigger. Provider-specific quota and permission statements must include official source, account scope, review date, and expiry/recheck policy; otherwise state them as unknown.
