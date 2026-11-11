# Runbook: database migrations, rollback and recovery

Applies to the PostgreSQL schema managed by Alembic (`migrations/`). Stage 1 ships a
single revision, `0001_initial`.

## Prerequisites

- `DATABASE_URL` points at the target PostgreSQL instance (see `.env.example`).
- Run from the repository root with the backend environment active:
  `pip install -e ".[dev]"`. Alembic reads `prepend_sys_path = services/api` and the
  runtime `DATABASE_URL` from application settings.

## Inspect state

```bash
alembic heads            # revisions declared in code
alembic current          # revision applied to the connected database
alembic history --verbose
```

## Apply migrations (forward)

```bash
alembic upgrade head             # to the latest revision
alembic upgrade 0001_initial     # to a specific revision
```

In Docker Compose the one-shot `migrate` service runs `alembic upgrade head` before `api`,
`worker` and `scheduler` start, so a normal `docker compose up` applies migrations
automatically.

Preview the SQL without touching the database:

```bash
alembic upgrade head --sql > /tmp/0001_initial.sql
```

## Rollback (backward)

```bash
alembic downgrade -1             # step back one revision
alembic downgrade base           # empty schema (removes all application tables)
```

`0001_initial.downgrade` drops `audit_log`, `sessions`, `memberships`, `users` and
`tenants` in dependency order. **Dropping the schema destroys all workspace data**; take a
backup first (below). Rollback is a maintenance action, not a routine operation.

Policy (SPEC.md section 11): every migration must be reviewed for forward and backward
safety before release. Prefer additive migrations (new nullable columns, new tables) over
destructive ones. A destructive change requires an explicit, tested backup/restore step.

## Backup

```bash
# logical backup (custom format, restorable and verifiable)
pg_dump --format=custom --no-owner \
  --dbname="$DATABASE_URL" \
  --file="backup-$(date +%Y%m%d-%H%M%S).dump"
```

Retain backups outside the database host. Backups contain recipient PII and provider
references, so store them encrypted and restrict access per
[docs/data-classification.md](../data-classification.md).

## Restore / recovery

1. Stop writers so no new data is written during recovery:

   ```bash
   docker compose -f infra/compose.yaml stop api worker scheduler
   ```

2. Restore into a clean database:

   ```bash
   createdb email_platform_restore      # or use a fresh role/db per environment
   pg_restore --no-owner --dbname="$RESTORE_DATABASE_URL" backup-YYYYMMDD-HHMMSS.dump
   ```

3. Verify schema and data before cutting over:

   ```bash
   DATABASE_URL="$RESTORE_DATABASE_URL" alembic current     # must show the expected head
   psql "$RESTORE_DATABASE_URL" -c "select count(*) from tenants;"
   ```

4. Point `DATABASE_URL` at the restored database, then restart:

   ```bash
   docker compose -f infra/compose.yaml up -d api worker scheduler
   ```

5. Confirm health: `GET /healthz` returns 200 and `GET /readyz` reports both `postgres`
   and `redis` healthy.

## Recovery drill

Before relying on this runbook in an incident, rehearse it against a scratch database:
back up, restore to a new database, run `alembic current`, and confirm the API reaches
`readyz` = `ok`. Record the date and result of the last drill.
