# Deployment and upgrade guide

Applies to the Phase 1 single-owner deployment: one API, one worker fleet, one
scheduler, PostgreSQL, Redis, S3-compatible object storage and the Next.js web
app. Compose is a **deployment baseline, not a high-availability guarantee**
(SPEC.md section 9); production should use managed PostgreSQL and object storage
where possible.

Related documents: [deployment-limits.md](deployment-limits.md) (tunables),
[runbooks/migrations.md](runbooks/migrations.md) (schema change procedure),
[runbooks/operations.md](runbooks/operations.md) (day-2 operations),
[threat-model.md](threat-model.md).

## 1. Topology

| Service | Role | Notes |
|---|---|---|
| `web` | Next.js UI | Terminates nothing; TLS ends at the operator's reverse proxy. |
| `api` | FastAPI (`app.main:app`) | Stateless; scale horizontally behind the proxy. |
| `worker` | Celery worker (`app.workers.celery_app`) | Idempotent task consumers. |
| `scheduler` | `python -m app.workers.scheduler` | **Exactly one active instance**; holds a PostgreSQL advisory lock (`SCHEDULER_ADVISORY_LOCK_KEY`). |
| `migrate` | one-shot `alembic upgrade head` | Runs before `api`/`worker`/`scheduler`. |
| `postgres` | system of record | Source of truth; Redis only transports. |
| `redis` | broker + cache | Rate gates and the Celery broker. |
| `object-storage` | S3-compatible | Local development uses `adobe/s3mock`; production uses a managed bucket. |

Restrict the database, Redis, object-storage and metrics ports to the private
network. Only the reverse proxy is public (ARCHITECTURE.md section 12).

## 2. Configuration and secrets

All configuration is environment or mounted-secret based; see
[`.env.example`](../.env.example) for the full annotated list.

- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `OBJECT_STORAGE_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_BUCKET` / `_REGION` / `_USE_TLS`
- `APP_BASE_URL`, `API_BASE_URL`, `SESSION_KEY`, `ENCRYPTION_KEY_REF`,
  `ENCRYPTION_KEY_VERSION`
- `OAUTH_GOOGLE_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`, `OWNER_GOOGLE_SUB` (preferred)
  or `OWNER_EMAIL`
- `METRICS_ENABLED`, `METRICS_TOKEN` (see section 6)

**Fail-closed startup.** With `APP_ENV=production` the API refuses to start when a
required secret is missing or an insecure default is in place
(`Settings.require_production_safety()`): a placeholder `SESSION_KEY`, missing
OAuth client, no owner identity, no external `ENCRYPTION_KEY_REF`, or a
non-HTTPS `APP_BASE_URL`. Fix the configuration; never weaken the check to get a
release out.

Never commit a real `.env`, a secret file, or secret values in Compose. Secret
envelope encryption stores a key version per credential; rotating the data key
means adding a new version, never rewriting history (ADR 0004).

## 3. First deployment

1. Copy `.env.example` to `.env` and fill it in; put secrets in a mounted file,
   not in the Compose file.
2. `docker compose -f infra/compose.yaml up -d --build`. `migrate` applies
   Alembic revisions, then `api`, `worker` and `scheduler` start, and the
   `createbucket` one-shot ensures the local bucket exists.
3. Confirm readiness: `GET /readyz` returns `200` with `postgres` and `redis`
   healthy; `GET /healthz` returns `{"status": "ok"}`.
4. Sign in through Google OAuth as the configured owner. The first login
   bootstraps the `personal` tenant, its membership and the owner user
   (`app/bootstrap.py`).
5. Register a provider account, add its credential, then **verify** the account
   and **refresh its quota** before any marketing send — routing excludes an
   account whose eligibility or capacity facts are unknown or stale.
6. Scrape `GET /metrics` from the monitoring host and confirm the exposition
   (section 6).

## 4. DNS and sender verification checklist

Provider-specific values are **external facts**: re-check them against the
provider's current documentation before enabling an adapter, and never hard-code
them as guarantees. For Resend, the authoritative pages are
`https://resend.com/docs/add-a-domain`, `.../domains/introduction`,
`.../domains/dmarc` and `.../domains/regions` (see
[provider-evaluation-resend.md](provider-evaluation-resend.md)).

- [ ] Choose the **sending subdomain** (e.g. `mail.example.com`) so reputation is
      isolated from the root domain's transactional mail.
- [ ] Add the **SPF** record the provider requires, exactly as published. A
      domain may carry only one SPF record.
- [ ] Add the **DKIM** records (public keys, selector) the provider publishes and
      wait for propagation.
- [ ] Add a **DMARC** record (`p=none` while monitoring, then tighten). DMARC
      requires SPF *or* DKIM alignment, so both must pass for the sending
      subdomain.
- [ ] Set the **provider-recommended custom Return-Path / MX** records if the
      provider requires them for bounce handling.
- [ ] Wait for the provider dashboard to report the domain **verified**; a
      pending domain cannot be marked eligible.
- [ ] Select the **sending region** deliberately (data residency and latency).
- [ ] After verification, run `POST /api/v1/provider-accounts/{id}/verify` so the
      platform records the verified sender domains as dated facts.
- [ ] Send a **test message** to an address you control and confirm SPF, DKIM and
      DMARC all pass in the raw headers.
- [ ] Confirm the provider **permits marketing/bulk** sending for the account and
      jurisdiction, and that the account's quota is recorded locally **no higher**
      than the provider states.

## 5. Upgrade and migration notes

Order for every release:

1. **Back up first.** Take an encrypted PostgreSQL backup and confirm it
   completed (section 7); never upgrade on the only copy.
2. **Check the migration plan.** Read [runbooks/migrations.md](runbooks/migrations.md).
   Every revision must have a reviewed forward and backward path, and any
   destructive step must be separated from the code deploy (expand → migrate →
   contract) rather than shipped in one step.
3. **Apply migrations with the code stopped or compatible.** Use an
   expand/contract sequence so the old and new code can both run against the
   schema during a rolling restart: add nullable columns/indexes first, backfill,
   switch reads/writes, then drop in a later release.
4. **Deploy `api`, `worker` and `scheduler` together.** A worker running older
   task signatures against a newer schema is the classic upgrade failure; drain
   the queue or deploy worker first when a task payload changes.
5. **Verify** `/readyz`, a test send, a webhook delivery, and that `/metrics`
   still renders after the restart.

Rollback: revert the code, then run `alembic downgrade` to the matching revision
only after the backup is confirmed. `0001_initial.downgrade` drops every
application table (see the migrations runbook) — downgrading is a maintenance
action, not a routine one.

## 6. Metrics endpoint exposure

`GET /metrics` renders Prometheus text exposition. It is **unauthenticated by
design** because it is meant to be scraped over the private network
(ARCHITECTURE.md section 12), with two switches:

- `METRICS_ENABLED=false` removes the endpoint (returns `404`).
- `METRICS_TOKEN=<secret>` requires `Authorization: Bearer <secret>`
  (constant-time comparison); anything else returns `401`.

Labels carry only platform-controlled, low-cardinality values — provider name,
event type, status, outcome, dataset. Recipient addresses, secrets and raw error
messages are never labels (SPEC.md section 8).

## 7. Backups and restore

- **Encrypted PostgreSQL backups** on a schedule, with the encryption key stored
  separately from the backup.
- **Objects**: enable provider versioning/lifecycle on the storage bucket for
  imports and assets.
- **Monitor completion and age** — never treat a process exit as success. Alert
  when the newest verified backup is older than the RPO window.
- **Restore drill**: periodically restore the newest backup into an isolated
  environment and run the smoke test (section 8). Record the date and outcome;
  a backup that has never been restored is an assumption, not a control.
- **RPO/RTO** are part of the deployment profile
  ([deployment-limits.md](deployment-limits.md) records them as "to be
  measured"); the retention jobs (`RETENTION_INTERVAL_SECONDS`) are independent
  of backup cadence.

## 8. Smoke test after any deployment

1. `GET /healthz` and `GET /readyz`.
2. Sign in; the workspace loads.
3. Import a small CSV to preview (never commit in this check).
4. Create a campaign, render a preview, send a test to an allowlisted address.
5. Confirm the webhook path: a delivered event appears and the ledger moves.
6. `GET /metrics` renders; queue-depth and webhook-lag gauges are present.
7. `GET /api/v1/provider-accounts/routing-status` shows the expected eligibility.

## 9. Responsibility assignment

| Area | Owner |
|---|---|
| Provider terms and acceptable-use compliance | Operator |
| Provider account eligibility, quota facts and review dates | Operator |
| Consent lawfulness and the accuracy of the contact list | Operator |
| Sender configuration (DNS, SPF/DKIM/DMARC, domains) | Operator |
| Retention periods and running the retention jobs | Operator |
| Backups, restore drills and RPO/RTO targets | Operator |
| Upgrade order, migration review and rollback decision | Operator |
| Secret/KMS ownership and credential rotation | Operator |

The platform enforces the *mechanisms* (fail-closed config, eligibility windows,
suppression, retention, pause controls); the operator owns the *decisions* above.
