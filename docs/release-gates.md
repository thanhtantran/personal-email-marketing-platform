# Release gates and Stage 7 exit-gate record

Recorded: 2026-11-13. Scope: Phase 1, single-owner. This file records what has
been **verified by execution** and, separately, what is a **process that must be
run by the operator** in a real environment. Nothing below is claimed as
executed unless it carries a result.

## 1. How to reproduce the automated checks

From the repository root:

```bash
python -m pytest tests -q          # unit/integration suite
ruff check services/api tests      # lint (E,F,I,B,UP,ASYNC,C4,SIM; line-length 100)
```

Environment used: Python 3.13 virtualenv (`.venv`), repository root
`personal-email-marketing-platform`. The suite is unit-level and does not require
PostgreSQL, Redis, object storage or a provider sandbox.

**Recorded results**

| Check | Result |
|---|---|
| `pytest tests` | **294 passed** |
| `ruff check services/api tests` | **All checks passed** |

## 2. Release gates (SPEC.md section 11)

| Gate | Status | Evidence |
|---|---|---|
| Migrations forward/backward strategy reviewed | Met (process) | [runbooks/migrations.md](runbooks/migrations.md); every revision ships a reviewed forward and backward path; destructive steps are separated from the code deploy. |
| No cross-tenant access | Met (mechanism + tests) | Tenant-scoped repositories; composite FKs; background tasks carry tenant ID and revalidate ownership. Covered by repository/tenant-scoping tests. |
| Ambiguous outcomes never blind-retried | Met (test) | `tests/unit/test_fault_injection.py` and `tests/unit/test_provider_gateway.py`: an ambiguous outcome reconciles and is never retried; reconciliation must prove non-acceptance first. |
| Unsubscribe/suppression invariant verified | Met (test) | Suppression records are idempotent upserts; complaint, hard bounce and unsubscribe create suppression regardless of campaign state; the reducer never revives a suppressed recipient. |
| Backup restore documented | Met (documentation) | [deployment.md](deployment.md) section 7 and [runbooks/operations.md](runbooks/operations.md) section 7. **The drill itself must be executed by the operator in an isolated environment** (section 4 below). |

## 3. Stage 7 exit gate

| Exit-gate item | Status | Evidence |
|---|---|---|
| Release gates in SPEC.md are met and recorded | Met | Section 2 above, with the one process item flagged. |
| Backup restore demonstrated in an isolated environment | **Not executed here** | Procedure documented; requires a real PostgreSQL instance and an isolated target. See section 4. |
| No unresolved critical/high security findings | Met (review) | Security review below; no unresolved critical/high findings. |
| Operational owner can pause sending and diagnose provider issues | Met (mechanism + docs) | Global pause and per-account disable endpoints; `routing-status` explains every exclusion; [runbooks/operations.md](runbooks/operations.md). |
| Documentation assigns responsibilities | Met | Responsibility table in [deployment.md](deployment.md) section 9 (provider terms, eligibility, consent lawfulness, sender configuration, retention). |

### Security review performed (Stage 7 task)

Reviewed in code and covered by tests or by explicit design decisions:

- **Authorization** — every tenant-scoped query goes through a tenant-scoped
  repository; ownership is revalidated in background tasks.
- **CSRF** — session cookie plus double-submit token; mutating endpoints depend on
  `verify_csrf`.
- **XSS** — HTML sanitizer allowlist (no scripts, forms, event attributes or
  user-controlled tracking endpoints); isolated preview origin supported.
- **SSRF / unsafe template URLs** — outbound calls are limited to the configured
  provider; template URLs are not fetched server-side.
- **File validation** — import size, row, column and field-length limits; staged
  objects are TTL-bound.
- **CSV formula injection** — spreadsheet-leading `= + - @` are escaped on export.
- **OAuth** — server-side state/nonce, exact redirect-URI allowlist,
  issuer/audience checks, stable `sub` identity; no token in browser storage.
- **Webhook replay** — signature/timestamp verification before durable
  acceptance, then a dedup key; replays are recorded and ignored
  (`WEBHOOK_INTAKE{result="duplicate"}`).
- **Secret redaction** — secrets are write-only; responses never carry a secret
  value; metrics labels exclude recipient addresses, secrets and raw errors.
- **Fail-closed configuration** — production startup refuses insecure defaults.

## 4. Requires a real environment (operator, not executed here)

These are **not** claimed as done. They need infrastructure that this
development environment does not have (no managed PostgreSQL, no monitoring
stack, no container scanner, no Node toolchain). Run them as part of the
deployment and record the outcome.

- **Backup restore drill** — take an encrypted backup, restore it into an
  isolated environment, run the smoke test ([deployment.md](deployment.md)
  section 8), record date, duration and result.
- **Migrations forward/backward rehearsal** — apply and roll back against a copy
  of real data before a production upgrade.
- **Monitoring stack wiring** — scrape `/metrics`, create the dashboards and
  alert rules from [runbooks/operations.md](runbooks/operations.md) section 3,
  then verify each trigger fires.
- **Dependency and container scanning** — run the scanner against the built
  images and the Python/npm dependency tree; record findings.
- **End-to-end flows against real services** — Google OAuth owner allowlist,
  provider sandbox send, real webhook delivery, CSV import commit.
- **Frontend build** — `next build` / `tsc` (no Node toolchain in this
  environment; the web app was reviewed by inspection only).
- **Load/throughput measurement** — the limits in
  [deployment-limits.md](deployment-limits.md) are provisional and marked "to be
  measured before locking".

## 5. Operator sign-off

| Role | Name | Date | Notes |
|---|---|---|---|
| Operator (Phase 1 single owner) | | | Confirms sections 1–3 above; completes section 4 and records results. |
