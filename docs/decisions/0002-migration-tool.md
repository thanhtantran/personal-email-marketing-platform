# 0002. Migration tool

- Status: Accepted
- Date: 2026-11-09

## Context

The schema is the backbone of the safety invariants (tenant scoping, composite constraints, event
dedupe). We need a migration tool that works with SQLAlchemy 2 and PostgreSQL and supports a
reviewable, explicit migration step.

## Decision

- Use **Alembic** with an async `env.py` that reads `DATABASE_URL` from application settings, so
  the app and migrations never disagree on the connection string.
- Migrations run through a dedicated one-shot `migrate` service in Compose (`alembic upgrade head`)
  before `api`/`worker`/`scheduler` start.
- Autogenerate is allowed but every revision is hand-reviewed: composite unique/FK constraints,
  partial indexes and `timestamptz` defaults are often not inferred correctly.
- Downgrade/forward strategy is reviewed per release; the recovery procedure is documented.

## Consequences

- Schema changes always ship as a reviewed revision plus any model changes.
- `prepend_sys_path = services/api` keeps `app.db.base` importable from the migration env.

## Alternatives considered

- Raw SQL migration scripts: rejected — weaker autogeneration and drift detection.
- Django-style migrations: not applicable to the chosen stack.

## Revisit trigger

A move to a different ORM or a managed migration service.
