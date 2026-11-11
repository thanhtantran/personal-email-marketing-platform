# 0005. Deployment target

- Status: Accepted
- Date: 2026-11-09

## Context

Phase 1 is a single-owner deployment. The team chose a local Docker Compose target for this
delivery, with production hardening handled later in Stage 7.

## Decision

- **Phase 1 target: Docker Compose on a single host** (local/self-hosted). Services: `web`, `api`,
  `worker`, `scheduler`, `postgres`, `redis`, `minio`, `migrate` (one-shot).
- TLS and public DNS are terminated by an **operator-managed reverse proxy**.
- Database, Redis, object storage and metrics ports are bound to the private network only.
- The scheduler runs as a single active instance using a database lease/advisory lock.
- A production single-owner profile (managed PostgreSQL/Redis, external secret manager, monitored
  encrypted backups) is added in Stage 7. Compose alone provides no high availability, failover or
  disaster recovery and this is documented.

## Consequences

- The local stack is the reference environment for development and acceptance tests.
- Operational readiness (backups, restore drills, monitoring) is a Stage 7 deliverable.

## Alternatives considered

- Kubernetes from the start: rejected — unjustified operational cost for a single-owner Phase 1.
- Serverless: rejected — long-running workers and a durable scheduler are required.

## Revisit trigger

Phase 2 SaaS, or measured availability/scaling needs beyond a single host.
