# 0003. Object storage

- Status: Accepted
- Date: 2026-11-09

## Context

Staged CSV uploads and optional template assets must be stored privately, with short-lived access
and a bounded retention window. The local deployment must work without cloud dependencies.

## Decision

- Use an **S3-compatible API** through `boto3`.
- Local/single-host: **MinIO** in Compose (private bucket created by a one-shot job).
- Production: managed object storage; credentials supplied via secret configuration.
- Uploads use a constrained, short-lived **signed URL**. Commit validates object ownership, digest
  and size before parsing. Staged objects are deleted after processing or the retention window.
- The bucket is private; anonymous access is disabled.

## Consequences

- Object keys are opaque and tenant-prefixed; no PII in key names.
- The API and workers share the same storage configuration.

## Alternatives considered

- Local filesystem storage: rejected — does not translate to the production topology and complicates
  retention/multi-process access.

## Revisit trigger

A change of storage backend or the introduction of per-tenant storage isolation in Phase 2.
