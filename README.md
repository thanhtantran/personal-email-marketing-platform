# Personal Email Marketing Platform

**English** | [Tiếng Việt](README-vi.md)

Self-hostable, single-owner email marketing application. Phase 1 targets one trusted operator who
manages consent-based audiences, builds MJML/GrapesJS templates, schedules campaigns, and routes
marketing email through explicitly eligible provider accounts while tracking provider-reported
outcomes. The data model is tenant-ready so a later Phase 2 can serve multiple isolated tenants.

## Contents

- [Current status](#current-status)
- [Documentation](#documentation)
- [Stack](#stack)
- [Services](#services)
- [Prerequisites](#prerequisites)
- [Quick start (local)](#quick-start-local)
- [Configuration](#configuration)
- [Local development without full Compose](#local-development-without-full-compose)
- [Tests and CI](#tests-and-ci)
- [Repository layout](#repository-layout)
- [Roadmap](#roadmap)
- [Guardrails (non-negotiable)](#guardrails-non-negotiable)
- [License](#license)

## Current status

Stage 0 (decisions and project foundation) and Stage 1 (runtime, persistence, and identity) are
complete. Implemented so far:

- Docker Compose stack: web, api, worker, scheduler, migration job, PostgreSQL 16, Redis 7, and a
  local S3-compatible object store.
- Settings validation with fail-closed production safety checks, structured request IDs, and safe
  logging defaults.
- `/healthz` (liveness) and `/readyz` (dependency-aware readiness, reporting PostgreSQL and Redis
  state accurately).
- Initial Alembic schema: tenants, users, memberships, sessions, and audit log; a single workspace
  tenant is bootstrapped at startup.
- Google OIDC login/callback with state validation, server-side sessions, logout/revocation, and a
  strict fail-closed owner allowlist.
- Tenant-scoped repository and service patterns with composite tenant-aware constraints.

Not yet wired: real login requires Google OAuth credentials and the owner identity (see
[Configuration](#configuration)). Audience, content, campaigns, and sending arrive in Stage 2+.

## Documentation

The source-of-truth documents live in [`docs/initials/`](docs/initials/):

| Document | Contents |
|---|---|
| [PRD.md](docs/initials/PRD.md) | Product requirements and acceptance criteria |
| [SPEC.md](docs/initials/SPEC.md) | Schema, API contracts, invariants, security, release gates |
| [ARCHITECTURE.md](docs/initials/ARCHITECTURE.md) | Service boundaries and deployment topology |
| [IMPLEMENTATION_PLAN.md](docs/initials/IMPLEMENTATION_PLAN.md) | Staged delivery plan |

Supporting material:

| Document | Contents |
|---|---|
| [docs/decisions/](docs/decisions/) | Architecture decision records (ADR 0001-0007) |
| [docs/threat-model.md](docs/threat-model.md) | Phase 1 threat model, reviewed each stage |
| [docs/data-classification.md](docs/data-classification.md) | Encryption, logging, retention, and access rules per data class |
| [docs/deployment-limits.md](docs/deployment-limits.md) | Provisional operator-tunable limits (not product guarantees) |
| [docs/provider-evaluation-resend.md](docs/provider-evaluation-resend.md) | First provider review (Resend) |
| [docs/deployment.md](docs/deployment.md) | Deployment, sender/DNS checklist, upgrade notes, backups |
| [docs/runbooks/migrations.md](docs/runbooks/migrations.md) | Migration, rollback, backup, and recovery runbook |
| [docs/runbooks/operations.md](docs/runbooks/operations.md) | Pause/diagnose, alerts, incident response, credential rotation |
| [docs/release-gates.md](docs/release-gates.md) | Release-gate and Stage 7 exit-gate record |

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 16 |
| Queue / cache | Redis 7 + Celery |
| Frontend | Next.js 14 (TypeScript), server-side session handling |
| Email design | GrapesJS + MJML |
| Object storage | S3-compatible (adobe/s3mock locally) |
| Deployment | Docker Compose (single owner) |

## Services

The backend is a modular monolith with independently run API, worker, and scheduler processes.

| Compose service | Role |
|---|---|
| `web` | Next.js UI |
| `api` | FastAPI HTTP API |
| `worker` | Celery worker |
| `scheduler` | Single-active scheduler |
| `migrate` | One-shot `alembic upgrade head`, runs before `api` starts |
| `createbucket` | One-shot bucket creation in the local object store |
| `postgres` | PostgreSQL 16 |
| `redis` | Redis 7 (broker/cache) |
| `object-storage` | S3-compatible store for private object uploads |

## Prerequisites

- Docker Desktop (with Compose v2)
- Python 3.12+ and Node.js 20+ (only for running tooling outside Docker)

## Quick start (local)

```bash
cp .env.example .env      # then fill in OAuth + owner identity values
docker compose -f infra/compose.yaml up --build
```

Services and default ports:

| Service | URL |
|---|---|
| web | http://localhost:3000 |
| api | http://localhost:8000 |
| api docs | http://localhost:8000/docs |
| object storage (S3) | http://localhost:9000 |
| postgres | localhost:5432 |
| redis | localhost:6379 |

Migrations run automatically via the one-shot `migrate` service before `api` starts, and
`createbucket` provisions the private upload bucket.

## Configuration

All configuration is environment/secret based. See [.env.example](.env.example) for names and safe
local placeholders. The application fails startup on missing production secrets or insecure
defaults. Never commit a real `.env` or provider credentials.

Minimum for a working login:

| Variable | Purpose |
|---|---|
| `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET` | Google OIDC client credentials |
| `OAUTH_GOOGLE_REDIRECT_URI` | Must match the Google console callback URL |
| `OWNER_GOOGLE_SUB` (preferred) or `OWNER_EMAIL` | The single owner allowed to sign in |
| `SESSION_KEY` | Session signing key, at least 32 bytes |

`SESSION_COOKIE_SECURE` may be left empty to auto-derive from the `APP_BASE_URL` scheme.

## Local development without full Compose

```bash
# backend
python -m venv .venv && .venv\Scripts\activate      # Windows PowerShell
pip install -e ".[dev]"
ruff check . && pytest

# frontend
npm install
npm run dev
```

## Tests and CI

```bash
ruff check .     # lint
pytest -q        # unit tests
npm run lint     # frontend lint
npm run typecheck
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the backend lint + unit tests and
the frontend lint + typecheck on every push to `main` and on pull requests.

## Repository layout

```text
apps/web/            Next.js UI
services/api/app/    FastAPI app, domain services, workers, providers, events, security
migrations/          Alembic migrations
infra/               compose.yaml, Dockerfiles, monitoring
packages/            shared frontend packages (api client, schemas)
docs/                initials, decisions, runbooks, provider evaluations
tests/               unit, integration, e2e, fixtures
```

## Roadmap

Delivery is dependency-ordered; see
[IMPLEMENTATION_PLAN.md](docs/initials/IMPLEMENTATION_PLAN.md) for tasks and exit gates.

| Stage | Focus | Status |
|---|---|---|
| 0 | Decisions and project foundation | Done |
| 1 | Runtime, persistence, and identity | Done |
| 2 | Audience, imports, consent, and suppression | Next |
| 3 | Content and templates | Planned |
| 4 | Campaign model, snapshots, and scheduling | Planned |
| 5 | Provider gateway and compliant capacity routing | Planned |
| 6 | Webhooks, unsubscribe, and analytics | Planned |
| 7 | Security hardening, operations, and release | Planned |
| - | Phase 2 multi-tenant SaaS | Out of scope for Phase 1 |

## Guardrails (non-negotiable)

- Contact storage is separated from sending capacity; provider quota is external and per
  provider-side account, never inferred from API-key count.
- Marketing sends require explicit, non-stale account eligibility; transactional-only accounts are
  ineligible.
- An ambiguous submit outcome becomes `unknown`; no blind retry or account failover.
- Suppression is authoritative and rechecked immediately before every provider submission.
- Quota, pricing, and permission facts are never hard-coded as product guarantees.

## License

Released under the [GNU Lesser General Public License v2.1](LICENSE).
