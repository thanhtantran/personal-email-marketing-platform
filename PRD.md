# Product Requirements Document (PRD)

**Product:** Personal Email Marketing Platform  
**Status:** Implementation baseline  
**Version:** 1.0  
**Related documents:** [SPEC.md](SPEC.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## 1. Product summary

A self-hostable email marketing application for an individual operator to manage audiences, design consent-based marketing email, schedule campaigns, and observe provider-reported outcomes. Phase 1 is a single-owner deployment. Its schema, authorization boundaries, and service APIs are tenant-ready so Phase 2 can support multiple organizations without rewriting core data ownership.

The product stores contacts without an application-imposed count cap; actual capacity is bounded by configured infrastructure, retention, and operational policy. Sending capacity is determined by each provider account's verified eligibility, quota, rate limits, reputation, and terms. Provider-account routing is for compliant capacity management and resilience. It must never rotate accounts or keys to evade quota, review, suspension, or provider restrictions.

## 2. Problem and goals

The motivating pain point is that a user can have remaining send quota but be prevented from sending because their audience exceeds a plan's contact limit. The product separates contact storage from sending capacity and makes both visible.

### Goals

1. Store and organize a large audience subject to infrastructure limits.
2. Import contacts safely and preserve consent/source evidence.
3. Build responsive email templates with GrapesJS and MJML output.
4. Create, preview, schedule, pause, and send campaigns to eligible recipients.
5. Route sends through explicitly configured provider accounts using quota, eligibility, rate, and health information.
6. Prevent known duplicates, honor suppressions and unsubscribe, and accurately represent uncertain provider outcomes.
7. Provide campaign analytics based on provider webhooks and first-party tracking where enabled.
8. Establish a tenant-aware data model and authorization design for Phase 2 SaaS.

### Non-goals for Phase 1

- Public multi-tenant SaaS, billing, plans, team roles, or customer support operations.
- Contact-count or send-quota circumvention, account farming, or provider-policy evasion.
- Guaranteed inbox placement, delivery, opens, or clicks.
- Transactional email product or general-purpose SMTP relay.
- Purchased/scraped lists, cold outreach automation, or consent acquisition.
- Advanced journey automation, A/B optimization, predictive send-time optimization, or CRM replacement.
- Arbitrary user-provided code execution in templates.

## 3. Users and primary workflows

**Primary user:** one trusted operator who deploys and administers the application. They may authenticate using Google OAuth. Phase 1 may allow only one owner identity; unauthorized identities are rejected.

### User stories

- As an owner, I can sign in with Google and only access my workspace.
- As an owner, I can upload a CSV, map fields, preview validation, resolve duplicates, and import contacts with source and consent metadata.
- As an owner, I can search, tag, filter, and define reusable segments without exporting data.
- As an owner, I can create a responsive template visually and inspect/edit its generated HTML safely.
- As an owner, I can compose a campaign, test-render personalization, send a test, and schedule it in a selected timezone.
- As an owner, I can see which provider accounts are eligible, their known quota/rate status, and why a campaign may be blocked.
- As an owner, I can pause/cancel queued work and distinguish accepted, delivered, bounced, complained, suppressed, and unknown outcomes.
- As a recipient, I can unsubscribe through a signed, one-click endpoint and stop receiving marketing mail promptly.
- As an owner, I can inspect an audit trail of imports, campaign actions, routing decisions, and suppression changes.

## 4. Scope and requirements

Priority: **P0** required for MVP; **P1** post-MVP; **P2** Phase 2.

### Identity and workspace

- **P0:** Google OAuth Authorization Code flow; validate issuer, audience, state, nonce, signature and expiry. Create an internal user from stable provider subject, not email alone.
- **P0:** Exactly one configured owner for Phase 1, with an explicit deployment setting. Fail closed for all other identities. Do not rely on obscurity of signup URLs.
- **P0:** Workspace is a first-class ownership boundary. All rows and queries include `tenant_id`; Phase 1 seeds one tenant and binds the owner to it.
- **P1:** Multiple authorized users and workspace roles.
- **P2:** SaaS organization onboarding, tenant administration, billing and support tooling.

### Audience and consent

- **P0:** CSV upload with size/row limits, UTF-8 handling, header mapping, preview, row-level error report, and asynchronous import for large files.
- **P0:** Normalize email for matching, enforce unique `(tenant_id, normalized_email)`, and retain original display value. Do not silently overwrite consent or custom fields on duplicates; provide explicit merge policy.
- **P0:** Contact status: `active`, `unsubscribed`, `suppressed`, `invalid`; store source, consent status, consent timestamp, and optional evidence/reference.
- **P0:** Tags and saved segments. Segment filters support standard fields, tags, and a documented subset of custom-field operators.
- **P0:** Global tenant suppression check immediately before provider submission; unsubscribe and complaint suppress future marketing sends.
- **P1:** Double opt-in signup form and consent evidence export.
- **P1:** Contact deletion/export workflows with documented retention treatment for suppression records.

### Templates and campaigns

- **P0:** GrapesJS visual builder with MJML-compatible components; save editor JSON, source MJML, rendered HTML, plaintext, and immutable campaign snapshot.
- **P0:** Sanitize HTML and URLs; disallow scripts, event handlers, iframes, unsafe CSS/URLs, and arbitrary external embeds. Preview desktop/mobile and send test message.
- **P0:** Campaign states: `draft`, `scheduled`, `preparing`, `sending`, `paused`, `completed`, `cancelled`, `failed`. Only draft/scheduled campaigns are editable; send-time content and audience snapshot are immutable.
- **P0:** Personalization supports an allowlisted set of contact fields with safe escaping and fallback values. Missing required values are reported before send.
- **P0:** Schedule by UTC instant plus original timezone/offset for display. Handle daylight-saving ambiguity by requiring a clear chosen offset.
- **P0:** Pause/cancel prevents future unsent submissions; an already accepted submission cannot be recalled.
- **P1:** Campaign duplication, reusable content blocks, A/B subject test.

### Sending gateway and provider accounts

- **P0:** Provider adapters implement a common contract; initially enable one adapter selected after implementation-time verification. Adding an adapter requires capability and webhook mapping documentation.
- **P0:** Store provider account separately from credential/API key. A provider account represents the provider-side account/domain/sending identity to which quota and eligibility attach. Multiple keys for one account do not create additional quota.
- **P0:** Explicit provider account configuration includes permitted message classes (`marketing`, `transactional`), verified sender/domain, account status, configured caps, known provider-reported quota, rate limits, health, and last verification time.
- **P0:** Marketing campaigns may only use an account explicitly verified as eligible for marketing by the operator and current provider policy. Transactional-only providers/accounts are ineligible for campaigns. Eligibility is not inferred from the existence of an API key.
- **P0:** Quota-aware routing selects only eligible accounts with known available capacity and healthy status. Unknown/stale quota means hold or require operator refresh; do not assume unlimited capacity. Configured local limits must not exceed provider-confirmed limits.
- **P0:** No cross-account retry after an ambiguous submit timeout unless provider idempotency or a reconciliation query proves the first attempt was not accepted. Mark `unknown`, reconcile, alert, and require a safe decision before replay.
- **P0:** Per-account and per-domain rate limiting; bounded retries only for classified transient failures and only where duplicate risk is controlled.
- **P1:** Multiple provider adapters, automated account health refresh, and operator-approved fallback policy.

Provider free-tier quotas, commercial terms, sender verification requirements, and marketing-email permissions vary and change. The product must not ship hard-coded claims about current quotas. Before enabling a provider, an operator must verify its current official terms, account-specific dashboard/API quota, and permission for the intended marketing use. Record that review and date; refresh it periodically and after provider notices.

### Analytics and event handling

- **P0:** Campaign summary counts for queued, submitted/accepted, delivered (only where provider reports it), bounced, complained, unsubscribed, suppressed, failed, and unknown.
- **P0:** Clearly distinguish provider acceptance from delivery. Opens and clicks are estimates affected by privacy features and scanners; label them accordingly.
- **P0:** Webhook verification, replay protection, idempotent event ingestion, event normalization, and tenant/provider-account scoping.
- **P1:** Click/open tracking through first-party redirect/pixel with disclosure and configurable disablement.

### Acceptance criteria

1. A non-owner Google identity cannot read or change any workspace resource; every API query is tenant-scoped.
2. An import preview shows accepted, duplicate, invalid, and missing-consent counts before commit; an interrupted import can resume without duplicate contacts.
3. A contact with unsubscribed/suppressed status never enters the provider submission path, including after being present in a previously built segment.
4. A campaign cannot be scheduled unless sender identity, marketing eligibility, consent policy, content checks, recipient estimate, and at least one compliant capacity path pass.
5. A send timeout after request transmission results in `unknown` until reconciliation; it is not blindly sent through another account.
6. Replayed webhook deliveries do not inflate analytics or repeat suppression actions.
7. A one-click unsubscribe updates suppression immediately and is honored by the next recipient eligibility check.
8. Cancel/pause halts future submissions while preserving already-provider-accepted results.
9. Credentials are encrypted at rest, never returned by read APIs, and redacted from logs and error traces.
10. Deployment documentation provides a reproducible single-owner Docker Compose setup, backup/restore procedure, and operational readiness checks.

## 5. Privacy, security, and compliance requirements

- The operator is responsible for lawful basis/consent, list provenance, required disclosures, and provider terms in each jurisdiction. Product workflows must capture evidence and block known suppressed recipients; they do not certify legal compliance.
- Support data minimization, export, deletion, retention configuration, and documented backup expiration.
- Encrypt transport with TLS at ingress; encrypt provider secrets using an external secret/key service where available or an application envelope key supplied outside the database. Rotate keys with version metadata.
- Secure, HTTP-only, SameSite cookies; CSRF protection; OAuth state/nonce; session rotation; restrictive CORS; CSP; rate limiting on auth and public endpoints.
- Verify webhooks using provider signatures/timestamps and constant-time comparison. Reject stale/replayed requests; retain raw payload only for a limited configurable period.
- Store consent and suppression state separately from campaign recipient snapshots. A campaign snapshot may retain recipient identifiers needed for audit but must not override current suppression.
- Restrict CSV file type/size, scan or parse safely, avoid formula execution in exports, and delete staged uploads after processing/retention window.
- Audit administrative changes and sensitive actions. Define incident response, breach handling, and restore drills before SaaS launch.

## 6. Success measures

- Import completion rate and percentage of rows with actionable errors.
- Campaign preparation time and send completion rate without duplicate submissions.
- Suppression/unsubscribe enforcement correctness.
- Provider outcome reconciliation rate and share of `unknown` messages resolved.
- Operational uptime, queue age, provider throttling, webhook processing lag, and backup restore success.

Do not optimize for raw send volume or open rate alone; prioritize consent integrity, reliable state, and complaint/bounce control.

## 7. Milestones

1. **Foundation:** Docker Compose, configuration/secrets, PostgreSQL migrations, Redis/Celery, Google OAuth, single-owner tenant bootstrap.
2. **Audience:** CSV preview/import, contacts, tags, segments, consent/suppression, audit events.
3. **Content:** GrapesJS/MJML editor, sanitizer/render pipeline, templates, test send.
4. **Campaign core:** immutable audience/content snapshots, scheduling, recipient ledger, pause/cancel, queue worker.
5. **Gateway:** one verified provider adapter, account eligibility/quota model, rate limits, idempotency and unknown reconciliation.
6. **Events and operations:** webhook ingestion, analytics, unsubscribe endpoint, monitoring, backups/restore runbook, security review.
7. **Phase 2 readiness:** tenant isolation audit, migration plan, roles, tenant quotas, billing boundaries, abuse response and support processes.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Provider disallows or limits marketing use | Verify official current terms and account approval before enablement; capability gate by account and message class. |
| Free-tier terms or quota change | Treat provider quotas as external, dynamic account state; no hard-coded marketing claims; stop routing on stale/unknown state. |
| Duplicate email after timeout | `unknown` outcome state, provider idempotency where supported, reconciliation, no blind failover. |
| Poor list quality damages reputation | Consent/source evidence, import validation, suppression, complaint/bounce thresholds, operator pause controls. |
| Unsubscribe races with a large campaign | Recheck suppression at dispatch time, bounded queue batches, cancellation checks and event ordering. |
| Tenant data leakage in future SaaS | Tenant key on every row, repository-scoped access, composite foreign keys, isolation tests and later PostgreSQL RLS review. |
| Tracking metrics are misleading | Label accepted/delivered/open/click semantics and document privacy/scanner caveats. |
| Contact storage grows unexpectedly | Infrastructure monitoring, configurable retention, database indexes/partitioning only when measured need arises. |

## 9. Phase 2 evolution

Introduce organization membership and roles, verified tenant provisioning, per-tenant quotas and billing, customer-managed provider accounts, tenant-level encryption strategy, abuse detection, support access controls, data export/deletion SLAs, RLS defense-in-depth, and isolated webhook routing. Preserve `tenant_id` in all tables and event envelopes from Phase 1. See [SPEC.md](SPEC.md) for schema/API constraints and [ARCHITECTURE.md](ARCHITECTURE.md) for service boundaries.
