# Software Design Specification (SPEC)

**Product:** Personal Email Marketing Platform  
**Status:** Implementation baseline  
**Version:** 1.0  
**Related documents:** [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## 1. Technical decisions

| Area | Decision |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2 async or sync consistently, Alembic |
| Database | PostgreSQL; JSONB for custom fields/provider payload references; tenant-scoped composite constraints |
| Queue/cache | Redis + Celery; PostgreSQL is source of truth, Celery is delivery mechanism only |
| Frontend | Next.js with TypeScript; server-side session handling; API client generated or typed from OpenAPI |
| Email design | GrapesJS editor; MJML source/rendering to responsive HTML; server-side sanitizer and deterministic snapshot |
| File storage | S3-compatible private bucket for staged imports and optional assets; short-lived signed URLs |
| Deployment | Docker Compose for single-owner deployment; reverse proxy/TLS supplied by operator |
| Auth | Google OAuth OIDC; internal user/session IDs; phase 1 owner allowlist |

Pin supported dependency versions in lockfiles at implementation time. Provider API versions and current terms must be checked against official documentation at adapter release; do not assume any listed provider supports marketing for every account or plan.

## 2. System invariants

1. Every business row belongs to exactly one `tenant_id`; no query may omit tenant context.
2. Phase 1 creates one tenant and one owner. Multi-tenancy is an architectural boundary, not an exposed signup feature.
3. `provider_account_id` represents the provider-side account/quota boundary. A credential is a secret used to access that account, not a quota unit.
4. Marketing eligibility is an explicit account capability with evidence and verification time. Transactional-only accounts cannot receive marketing campaign jobs.
5. A recipient is revalidated against current consent/suppression immediately before provider submission.
6. Provider acceptance is not delivery. Ambiguous submit outcomes become `unknown`; no automatic retry/failover without proof of non-acceptance or provider idempotency guarantee.
7. Campaign content, audience definition, and resolved recipient set are versioned snapshots at launch. Later contact edits do not silently change an in-flight campaign.
8. All externally delivered webhook events and internally consumed jobs are idempotent.
9. Provider quota/rate values are external and potentially stale. Never infer a quota from API-key count or claim that free tier is available.

## 3. Domain model and PostgreSQL schema

Use UUID primary keys, `timestamptz` in UTC, `created_at`/`updated_at`, and `tenant_id` on tenant-owned tables. Add composite unique/FK constraints where shown. Use soft delete only where restoration/audit requires it; document retention for each table.

### Core tables

- `tenants(id, slug, name, status, created_at)`
- `users(id, google_subject UNIQUE, email, display_name, status, created_at, last_login_at)`
- `memberships(tenant_id, user_id, role, status, created_at, PK(tenant_id,user_id))`; Phase 1 has one active owner.
- `sessions(id, tenant_id, user_id, token_hash, expires_at, revoked_at, created_at)`
- `contacts(id, tenant_id, normalized_email, email_display, status, consent_status, consent_at, consent_source, consent_evidence_ref, attributes JSONB, created_at, updated_at, deleted_at, UNIQUE(tenant_id,normalized_email))`
- `tags(id, tenant_id, name, normalized_name, UNIQUE(tenant_id,normalized_name))`
- `contact_tags(tenant_id, contact_id, tag_id, created_at, composite FKs to tenant-owned rows, UNIQUE(contact_id,tag_id))`
- `segments(id, tenant_id, name, definition JSONB, version, created_at, updated_at)`; definition is a validated AST, never raw SQL.
- `suppressions(id, tenant_id, normalized_email, reason, source, occurred_at, expires_at NULL, evidence JSONB, UNIQUE(tenant_id,normalized_email,reason))`
- `imports(id, tenant_id, uploaded_object_key, mapping JSONB, status, counts JSONB, idempotency_key, created_by, started_at, completed_at)`
- `import_rows(id, tenant_id, import_id, row_number, outcome, error_code, contact_id NULL, row_digest, UNIQUE(import_id,row_number))`; do not keep full CSV row indefinitely.
- `templates(id, tenant_id, name, editor_json JSONB, mjml_source TEXT, html TEXT, text_body TEXT, version, status, created_at, updated_at)`
- `provider_accounts(id, tenant_id, provider, external_account_ref, display_name, status, eligible_message_classes TEXT[], sender_domains JSONB, quota_state JSONB, limits JSONB, eligibility_verified_at, quota_refreshed_at, health_state, created_at, updated_at)`
- `provider_credentials(id, tenant_id, provider_account_id, secret_ciphertext, key_version, label, status, created_at, rotated_at)`; secret write-only to APIs.
- `campaigns(id, tenant_id, name, status, subject, from_name, from_email, reply_to, template_id, template_version, segment_id, scheduled_at, scheduled_timezone, launched_at, created_by, created_at, updated_at)`
- `campaign_snapshots(id, tenant_id, campaign_id, snapshot_version, content JSONB, audience_definition JSONB, recipient_count, created_at, UNIQUE(campaign_id,snapshot_version))`
- `campaign_recipients(id, tenant_id, campaign_id, contact_id NULL, email_snapshot, status, provider_account_id NULL, provider_message_id NULL, idempotency_key, attempt_count, next_attempt_at, accepted_at, outcome_at, error_code, created_at, updated_at, UNIQUE(campaign_id,email_snapshot), UNIQUE(tenant_id,idempotency_key))`
- `send_attempts(id, tenant_id, recipient_id, provider_account_id, attempt_no, request_digest, provider_message_id NULL, state, started_at, finished_at, error_class, response_code, UNIQUE(recipient_id,attempt_no))`
- `webhook_events(id, tenant_id, provider_account_id, provider_event_id, event_type, occurred_at, received_at, payload_digest, payload_object_key NULL, processed_at, status, UNIQUE(provider_account_id,provider_event_id))`
- `message_events(id, tenant_id, campaign_id, recipient_id, provider_account_id, event_type, event_key, occurred_at, source, metadata JSONB, UNIQUE(tenant_id,event_key))`
- `audit_log(id, tenant_id, actor_user_id NULL, action, object_type, object_id, request_id, created_at, details JSONB)`

`contacts.status` and `consent_status` are distinct: a valid address may lack marketing consent. Suppression is authoritative even if contact fields or a snapshot disagree. `campaign_recipients.email_snapshot` is retained only as needed for campaign audit/analytics and must follow configured retention/deletion policy.

### Indexes

Create indexes on `(tenant_id, status)`, `(tenant_id, normalized_email)`, `(tenant_id, campaign_id, status)`, `(tenant_id, next_attempt_at)`, `(provider_account_id, occurred_at)`, `(tenant_id, contact_id)`, GIN for supported JSONB attributes only after query patterns are fixed. Avoid broad JSONB query API. Partition high-volume event tables only after measured volume supports it.

## 4. API outline

Prefix `/api/v1`. Require authenticated session, CSRF token for cookie-authenticated mutations, tenant context resolved from active membership (never accepted as trusted body input), and request ID. Use cursor pagination. Return RFC 7807-style errors with stable codes.

| Method/path | Purpose |
|---|---|
| `GET /auth/google/start`, `GET /auth/google/callback`, `POST /auth/logout` | OAuth/session |
| `GET /me`, `GET /workspace` | Identity and active workspace |
| `POST /imports` / `POST /imports/{id}/commit` / `GET /imports/{id}` | Upload/preview/commit import |
| `GET/POST /contacts`, `GET/PATCH/DELETE /contacts/{id}` | Contact management |
| `GET/POST /segments`, `GET /segments/{id}/estimate` | Validated segment definitions and estimates |
| `GET/POST /templates`, `GET/PATCH/DELETE /templates/{id}`, `POST /templates/{id}/render` | Template lifecycle/render |
| `GET/POST /provider-accounts`, `POST /provider-accounts/{id}/verify`, `POST /provider-accounts/{id}/refresh-quota` | Operator config; secret write-only |
| `GET/POST /campaigns`, `GET/PATCH /campaigns/{id}` | Draft management |
| `POST /campaigns/{id}/validate`, `/test-send`, `/schedule`, `/launch`, `/pause`, `/resume`, `/cancel` | Campaign actions with explicit transitions |
| `GET /campaigns/{id}/analytics`, `GET /campaigns/{id}/recipients` | Aggregate outcomes and paged ledger |
| `GET /unsubscribe/{signed_token}`, `POST /unsubscribe/{signed_token}` | Public signed one-click unsubscribe; no PII in URL |
| `POST /webhooks/{provider}/{account_public_id}` | Provider-signed webhook intake |

Mutating create/launch/import endpoints accept `Idempotency-Key`; persist key, tenant, request hash, and result. Reuse with different request body returns `409`. Never return credential ciphertext/plaintext. Upload endpoint issues a constrained private object key and short-lived upload URL; commit validates object ownership and digest.

## 5. Campaign lifecycle and worker flow

### Prepare and schedule

1. API validates draft fields, sender/domain verification state, template sanitation, personalization variables, consent policy, and segment definition.
2. Estimate eligible audience by excluding invalid, unsubscribed, suppressed, and non-consenting contacts. Estimate is informational until launch revalidation.
3. At schedule/launch, transactionally lock campaign, enforce legal state transition, build immutable content/audience snapshot, create recipient ledger in bounded batches, and enqueue an outbox record.
4. Outbox dispatcher publishes Celery tasks; mark each event published idempotently. PostgreSQL outbox avoids DB-commit/queue-publish gap.
5. Scheduler uses persisted UTC `scheduled_at`, finds due campaigns with `FOR UPDATE SKIP LOCKED`, and advances state once.

### Dispatch one recipient

1. Lock eligible recipient row; check campaign active, retry due, and current tenant suppression/consent/contact status.
2. Obtain provider account candidates explicitly eligible for `marketing`, sender domain and region, health, freshness, remaining provider-confirmed/local quota, and rate limiter.
3. Reserve a quota unit atomically in local accounting. Use Redis token bucket for throughput and a DB reservation to avoid concurrent over-allocation; reconcile reservations from provider results.
4. Persist `send_attempt` before network call with stable recipient idempotency key. Do not hold DB transaction open across HTTP request.
5. Submit with provider idempotency key if supported. Definitive acceptance -> `accepted` with provider ID. Definitive transient rejection -> bounded retry with exponential backoff+jitter, `Retry-After` support, and same safe identity where provider semantics allow. Permanent rejection -> `failed`.
6. Timeout/connection loss after request may have reached provider -> `unknown`; stop automatic send. Reconcile by provider lookup/webhook/idempotency API. Only retry after confirmed non-acceptance; if not reconcilable, operator resolves with duplicate-risk warning.
7. On hard bounce/complaint/unsubscribe webhook, create suppression idempotently. Recheck suppression immediately before each later submission.

### Retry rules

- Retry only classified transient failures (e.g. explicit throttling or service-unavailable response) and within configured attempt/time limits.
- Honor provider `Retry-After`; exponential delay with jitter and a circuit breaker when repeated provider failures occur.
- Never retry validation/authentication/policy rejections automatically.
- Never route an ambiguous attempt to a different account to get around an account limit or suspected review.
- Campaign pause/cancel is checked before each submission; already accepted messages remain in ledger.

## 6. Provider adapter and routing contract

```python
class ProviderAdapter(Protocol):
    async def verify_account(self, credential: Secret, account_ref: str) -> AccountVerification: ...
    async def refresh_capacity(self, credential: Secret) -> CapacitySnapshot: ...
    async def send(self, credential: Secret, message: OutboundMessage,
                  idempotency_key: str | None) -> SubmitResult: ...
    def verify_webhook(self, headers: Mapping[str, str], body: bytes, secret: Secret) -> bool: ...
    def normalize_webhook(self, body: bytes) -> list[NormalizedProviderEvent]: ...
    async def reconcile(self, credential: Secret, provider_message_id: str | None,
                        idempotency_key: str) -> ReconciliationResult: ...
```

`SubmitResult` is one of `accepted`, `definitive_transient_rejection`, `definitive_permanent_rejection`, `ambiguous`. A provider adapter documents which HTTP outcomes are definitive, idempotency scope/retention, quota/account endpoints, event mapping, signature scheme, marketing eligibility evidence, and limitations. Router uses policy, not random round robin: select eligible capacity by configured priority/weighted share while respecting all caps. No credential-only rotation. An account with stale/unknown quota, unverified marketing eligibility, unhealthy state, or exceeded rate is excluded.

Free plan quota and permission are not assumed by the application. Operator records official documentation/review date and account-specific evidence; adapter verification refreshes observable facts but cannot decide contractual eligibility on its own.

## 7. Event model and analytics semantics

Internal event envelope: `event_id`, `event_type`, `tenant_id`, `occurred_at`, `recorded_at`, `actor_id` (nullable), `aggregate_type`, `aggregate_id`, `correlation_id`, `schema_version`, `data`.

Normalized recipient events: `queued`, `submitted` (provider accepted request), `delivered` (provider-reported), `deferred`, `bounced_soft`, `bounced_hard`, `complained`, `unsubscribed`, `rejected`, `unknown`, `opened`, `clicked`. Keep raw provider event name in metadata. Provider event IDs are dedup keys; when absent, derive a stable digest from provider account + canonical payload + event type/time/recipient fields with documented collision tradeoff.

Delivery event may arrive before API response or out of order. State reducer must be monotonic where possible and retain all events; a later authoritative event can resolve `unknown`. Complaint/hard bounce/unsubscribe creates suppression regardless of campaign state. Analytics use deduplicated event rows and expose distinct recipients and total events separately. Opens/clicks may be privacy-proxied or scanner-generated and are not proof of human engagement.

## 8. Security and privacy implementation

- OAuth uses server-side state/nonce, PKCE if supported by selected client flow, exact redirect URI allowlist, issuer/audience checks, and stable `sub` identity. No access token in browser storage.
- Session cookie: `Secure`, `HttpOnly`, `SameSite=Lax` or stricter where compatible, short idle/absolute expiry, rotation after login, revocation on logout.
- Secret envelope encryption: data key encrypted by KMS/secret manager key in production; local development may use mounted secret file. Store key version; never commit secrets or put them in Compose values tracked in source.
- Webhook route performs signature/timestamp verification before durable acceptance, then queues normalized processing. Keep raw payload minimal and TTL-bound.
- Protect CSV import/export from formula injection; escape spreadsheet-leading `= + - @` on export. Limit decompression, rows, columns, field length and file size.
- Sanitizer allowlist for HTML, attributes, protocols, styles; no scripts, forms, event attributes or user-controlled tracking endpoints. Use isolated preview origin where practical.
- Apply authorization in service/repository layer and optionally PostgreSQL RLS in Phase 2. Composite FKs prevent cross-tenant references. Background tasks carry tenant ID and revalidate ownership.
- Avoid recipient addresses in general logs, tracing labels, URLs, and metrics. Use redacted identifiers/digests.

## 9. Deployment and configuration

Docker Compose services: `web` (Next.js), `api` (FastAPI), `worker` (Celery), `scheduler` (single active scheduler with DB lock), `postgres`, `redis`, optional `minio` for local S3-compatible storage, and `migrate` one-shot job. Production should use managed PostgreSQL/object storage where possible; Compose is a deployment baseline, not a high-availability guarantee.

Configuration via environment/secret mounts: `DATABASE_URL`, `REDIS_URL`, `OBJECT_STORAGE_*`, `OAUTH_GOOGLE_CLIENT_ID`, secret references, `APP_BASE_URL`, `SESSION_KEY`, `ENCRYPTION_KEY_REF`, `OWNER_GOOGLE_SUB` (preferred) or verified owner email, `DEFAULT_TIMEZONE`, import limits, tracking setting, retention durations, per-account local limits. Fail startup on missing production secrets or insecure defaults. Health checks distinguish liveness/readiness; migration is explicit and backups are scheduled.

Backups: encrypted PostgreSQL backups with tested restore; object version/lifecycle policy for imports/assets; backup encryption keys stored separately. Define RPO/RTO in deployment profile. Never claim successful backup solely from process exit; monitor completion and periodically restore into isolated environment.

## 10. Observability and operations

Structured logs with request/correlation/campaign/provider-account IDs (no secrets or raw recipient PII); OpenTelemetry traces across API, DB, queue, provider request and webhook. Metrics: queue depth/age, campaign recipients by state, `unknown` age, provider latency/error/throttle, capacity staleness, rate-limit wait, webhook lag/verification failures, import failure rate, DB/Redis health, storage and backup age.

Alerts: rising unknown outcomes, complaint/hard-bounce threshold, stale capacity, provider auth/policy rejection, queue backlog, webhook signature anomaly, failed backups, disk/storage exhaustion. Provide global pause switch and per-account disable. Audit every operator intervention and account capability/limit change.

## 11. Testing and release gates

Testing is part of the implementation plan; this specification defines required coverage, without asserting that tests have been run.

- Unit: normalization, consent/suppression policy, segment AST, quota reservation, retry classification, state machine, personalization escaping, event reducer.
- Integration: PostgreSQL migrations/constraints, tenant isolation, outbox dispatch, Redis rate limit, object upload lifecycle, webhook replay/signature, provider adapter contract using mocks/sandbox.
- End-to-end: OAuth owner allowlist, CSV preview/commit, create/render/test/schedule/pause campaign, unsubscribe, analytics update.
- Fault injection: timeout before/after provider acceptance, duplicate tasks/webhooks, provider throttling, stale quota, worker crash between DB and queue, cancellation during batch.
- Security: authorization matrix, CSRF/XSS, SSRF and unsafe template URLs, CSV formula injection, secret/log leakage, webhook spoof/replay, dependency/container scanning.
- Release gates: migrations forward/backward strategy reviewed; no cross-tenant access; ambiguous outcomes never blind-retried; unsubscribe/suppression invariant verified; backup restore documented.

## 12. Migration path to Phase 2

1. Keep tenant IDs non-null from initial migration; seed `personal` tenant and map existing owner.
2. Replace single owner configuration with membership-based authorization behind a feature flag; retain tenant-scoped repository interfaces.
3. Add tenant onboarding/invitation, roles, tenant limits, billing and abuse controls; do not expose public registration before operational processes exist.
4. Audit every query/task/webhook for tenant context; add RLS policies and test connection-pool tenant reset behavior before relying on RLS.
5. Add customer data export/deletion, retention controls, support audit, per-tenant encryption/key strategy, billing isolation and incident response.
6. Scale workers independently; partition event tables only using measured volume and tested migration/backfill plan.

## 13. Open implementation decisions (must be recorded before coding affected module)

- Select and validate the first provider adapter against current official API docs, marketing permission, account quota APIs, idempotency/reconciliation behavior, webhooks and jurisdiction.
- Choose managed secret/KMS implementation for production and define rotation runbook.
- Set explicit retention periods, import limits, batch size, rate ceilings, and complaint/bounce circuit-breaker thresholds for the deployment.
- Select sender identity verification and required DNS checks; maintain DNS setup help text from authoritative current sources.
- Decide whether open/click tracking is enabled by default based on privacy review and jurisdictions served.
