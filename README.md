# Personal Email Marketing Platform

Self-hostable, single-owner email marketing application. Phase 1 target: one trusted operator
manages consent-based audiences, builds MJML/GrapesJS templates, schedules campaigns, and routes
marketing email through explicitly eligible provider accounts while tracking provider-reported
outcomes. The data model is tenant-ready for a later Phase 2 SaaS.

Source of truth documents:

- [PRD.md](PRD.md) - product requirements and acceptance criteria
- [SPEC.md](SPEC.md) - schema, API contracts, invariants, security, release gates
- [ARCHITECTURE.md](ARCHITECTURE.md) - service boundaries and deployment topology
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) - staged delivery plan
- [docs/decisions/](docs/decisions/) - architecture decision records
- [docs/provider-evaluation-resend.md](docs/provider-evaluation-resend.md) - first provider review

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 16 |
| Queue / cache | Redis 7 + Celery |
| Frontend | Next.js (TypeScript), server-side session handling |
| Email design | GrapesJS + MJML |
| Object storage | S3-compatible (adobe/s3mock locally) |
| Deployment | Docker Compose (single owner) |

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

Migrations run automatically via the one-shot `migrate` service before `api` starts.

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

## Repository layout

```text
apps/web/            Next.js UI
services/api/app/    FastAPI app, domain services, workers, providers, events, security
migrations/          Alembic migrations
infra/               compose.yaml, Dockerfiles, monitoring
packages/            shared frontend packages (api client, schemas)
docs/                decisions, runbooks, provider evaluations
tests/               unit, integration, e2e, fixtures
```

## Configuration

All configuration is environment/secret based. See [.env.example](.env.example) for names and safe
local placeholders. The application fails startup on missing production secrets or insecure
defaults. Never commit a real `.env` or provider credentials.

## Guardrails (non-negotiable)

- Contact storage is separated from sending capacity; provider quota is external and per
  provider-side account, never inferred from API-key count.
- Marketing sends require explicit, non-stale account eligibility; transactional-only accounts are
  ineligible.
- An ambiguous submit outcome becomes `unknown`; no blind retry or account failover.
- Suppression is authoritative and rechecked immediately before every provider submission.
- Quota, pricing, and permission facts are never hard-coded as product guarantees.
