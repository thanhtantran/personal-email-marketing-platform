# 0004. Secret envelope encryption

- Status: Accepted
- Date: 2026-11-09

## Context

Provider credentials and other secrets must be encrypted at rest, never returned by read APIs, and
redacted from logs. A single-owner deployment still benefits from versioned keys and a clean
rotation story.

## Decision

- **Envelope encryption** using AES-256-GCM. Each secret is encrypted with a data key; the data key
  is supplied outside the database via `ENCRYPTION_KEY_REF`.
- Local development: key material mounted from a secret file (`file://...`).
- Production: an external KMS/secret manager reference (to be selected before production).
- Store a `key_version` alongside each ciphertext; decryption selects the matching key.
- Secrets are **write-only**: APIs accept secret values on write and never return plaintext or
  ciphertext. Ciphertext, keys and derived values are redacted from logs, traces and errors.
- Rotate keys with version metadata; re-encrypt on rotation.

## Consequences

- Startup fails if required production secrets are missing or set to insecure defaults.
- The running process needs access to key material; it is never persisted in the database.

## Alternatives considered

- Column-level database encryption with the key stored in the DB: rejected — protects against
  nothing meaningful and complicates rotation.

## Revisit trigger

Selecting the concrete production KMS/secret manager, or the Phase 2 per-tenant key strategy.
