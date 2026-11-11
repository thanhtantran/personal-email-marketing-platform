# Provisional deployment limits

These are **operator-tunable settings, not product guarantees**. They are set in configuration
(see `.env.example`) and refined as measurements are available. No limit may be presented as a
provider quota; provider quotas are external, dated account facts (see
[provider-evaluation-resend.md](provider-evaluation-resend.md)).

| Setting | Default | Rationale |
|---|---|---|
| `IMPORT_MAX_FILE_MB` | 50 | Bound staging upload and parse cost; large imports run asynchronously. |
| `IMPORT_MAX_ROWS` | 200,000 | Bound worker memory/time per import. |
| `IMPORT_MAX_COLUMNS` | 100 | Reject pathological CSVs. |
| `IMPORT_MAX_FIELD_LENGTH` | 4,096 | Bound per-cell size; prevent parser abuse. |
| `CAMPAIGN_BATCH_SIZE` | 500 | Recipient ledger batch size; balances throughput and cancellation responsiveness. |
| `SEND_REQUEST_TIMEOUT_SECONDS` | 30 | Provider request timeout; keep below provider/proxy limits. |
| `SEND_MAX_ATTEMPTS` | 5 | Bounded retries for classified transient failures only. |
| `RATE_LIMIT_AUTH_PER_MINUTE` | 20 | Protects auth/public endpoints. |
| `RAW_WEBHOOK_RETENTION_DAYS` | 14 | Minimal raw payload retention window. |
| `STAGED_UPLOAD_RETENTION_DAYS` | 7 | Delete staged import objects promptly. |
| `IMPORT_ROW_RETENTION_DAYS` | 90 | Retain row outcomes briefly, not full CSV rows indefinitely. |

## Provider capacity (external, not a product fact)

- Per provider-side **account/domain**, with an operator-recorded review date and evidence.
- Configured local caps **must not exceed** provider-confirmed limits.
- Stale/unknown capacity blocks routing; the operator refreshes it explicitly.
- Adding API keys never increases quota.

## To be measured before locking

- Actual import throughput and memory at representative sizes.
- Safe recipient send rate per provider account and domain.
- Complaint/bounce circuit-breaker thresholds (start conservative, e.g. well below provider AUP
  limits; Resend AUP references complaint < 0.08% and bounce < 4% — verify current values).
- RPO/RTO objectives and backup cadence for the Stage 7 production profile.
