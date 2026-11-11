# Data classification

Drives encryption, logging, retention and access rules. Reviewed each stage.

| Class | Examples | Storage | Logging | Retention |
|---|---|---|---|---|
| **Secret** | Provider API keys, `SESSION_KEY`, encryption keys, OAuth client secret | Encrypted (envelope); key material outside DB | Never logged, never returned by APIs | Rotated; ciphertext retained per policy |
| **Confidential – consent/suppression** | Consent status/source/timestamp, consent evidence ref, suppression reason, unsubscribe events | DB, tenant-scoped | Identifiers/digests only | Suppression retained to honor opt-outs; evidence per policy |
| **Personal data (PII)** | Recipient email (`email_display`, `normalized_email`), contact attributes, provider message IDs | DB, tenant-scoped; `email_snapshot` only as needed for audit | Never log raw address; use opaque IDs/digests | Configurable; snapshots follow campaign retention |
| **Internal** | Campaign content, template versions, routing decisions, audit log, analytics counts | DB | IDs and counts ok | Per policy |
| **Restricted – raw provider payloads** | Raw webhook bodies, staged CSV objects | Object storage (private) + limited DB refs | Never logged | `RAW_WEBHOOK_RETENTION_DAYS`, `STAGED_UPLOAD_RETENTION_DAYS` |
| **Public** | App health status, non-sensitive UI copy | Any | ok | n/a |

## Rules

- Personal data is never placed in URL paths/query strings, metric labels, log messages or traces.
  Use opaque recipient references and digests.
- Secrets are write-only across every API and are redacted from error traces.
- Retention periods are configuration, not constants; deletion jobs purge by class.
- Backups inherit the strictest class they contain and must be encrypted.

## Provisional retention defaults (operator-tunable)

See [deployment-limits.md](deployment-limits.md): raw webhook payloads 14 days, staged uploads
7 days, import rows 90 days.
