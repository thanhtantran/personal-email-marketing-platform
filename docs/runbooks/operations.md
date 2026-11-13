# Runbook: operations (pausing, diagnosing, alerts, incidents, rotation)

Day-2 operations for the Phase 1 deployment. Read alongside
[../deployment.md](../deployment.md) (topology, smoke test),
[./migrations.md](./migrations.md) (schema changes) and
[../threat-model.md](../threat-model.md).

Every operator intervention that changes sending behaviour is written to the
audit log (`audit_log`): global pause/resume, account status and capability
changes, credential add/revoke. Use the audit trail as the record of what was
done and when.

## 1. Stop sending

Two independent controls; use the narrowest one that solves the problem.

**Global marketing pause** (tenant-wide, immediate):

```http
POST /api/v1/provider-accounts/routing-pause
{ "paused": true, "reason": "operator: investigating complaint spike" }
```

- Blocks new marketing submissions for the whole tenant; the dispatcher stops a
  batch and leaves un-submitted recipients in place (they are not lost).
- Messages already accepted by the provider are unaffected.
- The reason is stored and surfaced by `GET /api/v1/provider-accounts/routing-status`.
- Resume with `{"paused": false, "reason": "..."}` once the cause is resolved.

**Per-account disablement** (one provider account):

```http
PATCH /api/v1/provider-accounts/{account_id}
{ "status": "disabled" }
```

- Excludes the account from routing (`EXCLUSION_NOT_ACTIVE`) while other healthy
  accounts keep serving. Use this for one bad credential, one burned domain, or
  one account under provider review.

**Per-campaign pause**: `POST /api/v1/campaigns/{campaign_id}/pause` stops new
submissions for that campaign only.

## 2. Diagnose why sending stopped

| Question | Where to look |
|---|---|
| Can any marketing traffic route? | `GET /api/v1/provider-accounts/routing-status` → `marketing_paused`, `marketing_eligible`, `capacity_fresh`, `exclusions`. |
| Which accounts are excluded and why? | Same response: each exclusion carries an `account_id`, `provider` and `reason` (`not_active`, `class_not_eligible`, `eligibility_unverified`, `eligibility_stale`, `unhealthy`, `capacity_stale`, `capacity_unknown`, `quota_exhausted`, `credential`, `sender_domain`). |
| Is the queue stalled? | `email_platform_outbox_events{status="pending"}` rising and `email_platform_outbox_oldest_pending_age_seconds` climbing. |
| Are webhooks lagging? | `email_platform_webhook_events{status="received"}` and `email_platform_webhook_oldest_unprocessed_age_seconds`. |
| Are provider requests failing/throttled? | `email_platform_provider_submissions_total` by `outcome`; `email_platform_provider_submit_seconds` latency. |
| Is an account unhealthy? | `email_platform_provider_accounts{status,health_state}`; the account's `health_state` moves to `degraded`/`unhealthy` on quota/auth/policy rejections. |
| Is the ledger piling up in one state? | `email_platform_campaign_recipients{status="unknown"}` (needs reconciliation) or `status="retry"`. |

Common causes and the fix:

- **`capacity_unknown` / `capacity_stale`** → refresh the facts:
  `POST /api/v1/provider-accounts/{id}/refresh-quota`. Unknown never counts as
  available capacity.
- **`eligibility_stale` / `eligibility_unverified`** → re-verify:
  `POST /api/v1/provider-accounts/{id}/verify`.
- **`credential`** → the credential is missing, revoked or cannot be decrypted;
  add a new credential (`POST .../credentials`) or check the encryption key
  version.
- **`quota_exhausted`** → the account's dated facts say the daily/monthly limit
  is spent; wait for the next window or raise the local cap **only** if the
  provider confirms more headroom.
- **`no_route` on recipients** → the send was deferred (not dropped); it retries
  after `PROVIDER_ROUTING_DEFER_SECONDS`.

Ambiguous outcomes (`status="unknown"`) are **never** auto-resubmitted: the
gateway records a `send_attempt` in state `unknown` and reconciliation must first
confirm the earlier request was not accepted before a retry is allowed
(SPEC.md invariant 6).

## 3. Alert thresholds

The platform exposes the inputs; alerting thresholds are an operator decision.
Suggested starting points (tune against measured traffic; they are **not**
provider guarantees):

| Alert | Signal | Start conservative |
|---|---|---|
| Rising unknown outcomes | `increase(email_platform_provider_submissions_total{outcome="ambiguous"}[15m])` | any sustained increase; page |
| Provider auth/policy rejection | `...{outcome="definitive_permanent_rejection"}` + account `health_state` unhealthy | page immediately |
| Provider throttling | `...{outcome="definitive_transient_rejection"}` and `retry_after` | page on sustained rate |
| Complaint threshold | suppression inserts with reason `complaint` | well below the provider AUP limit — verify the current figure from the provider |
| Hard-bounce threshold | suppression inserts with reason `hard_bounce` | well below the provider AUP limit — verify the current figure |
| Stale capacity | account `capacity_fresh=false` | warn |
| Queue backlog | `email_platform_outbox_oldest_pending_age_seconds` above a few minutes, or pending depth above `CAMPAIGN_OUTBOX_BATCH_SIZE` | warn, page if sustained |
| Webhook lag | `email_platform_webhook_oldest_unprocessed_age_seconds` climbing | warn |
| Webhook signature anomaly | `increase(email_platform_webhook_intake_total{result="rejected"}[5m])` | page — possible spoofing |
| Metrics collection failing | `email_platform_metrics_collection_errors_total` non-zero | warn — some gauges are stale |
| Failed backup | backup job status/age | page |
| Storage/disk exhaustion | object store and volume usage | warn then page |

## 4. Incident response basics

1. **Stop the bleeding.** Pause globally (section 1) or disable the affected
   account. Stopping sending is always safe: in-flight state is durable and no
   recipient is lost.
2. **Preserve evidence.** Capture the `/metrics` snapshot, the affected campaign
   and provider-account IDs, the relevant `audit_log` rows, and the webhook rows
   (`webhook_events`) — the raw payload is TTL-bound, so preserve what you need
   before it ages out.
3. **Scope it.** Which campaigns, accounts, recipients and time window? Is it one
   account, one domain, or tenant-wide? Did it affect delivery, suppression, or
   analytics only?
4. **Classify.** Security (spoofed/replayed webhook, credential leak, cross-tenant
   access), provider (auth/policy/quota/throttle), or platform (worker crash,
   queue stall, bad deploy).
5. **Fix and verify.** Apply the narrowest fix, then verify with the smoke test
   ([../deployment.md](../deployment.md) section 8) before resuming.
6. **Resume** with an explicit reason, then record the incident: cause, blast
   radius, decision, and follow-up.

Never "fix" a delivery problem by removing suppression. Complaint, hard-bounce
and unsubscribe records are authoritative and idempotent.

## 5. Credential rotation (provider API keys)

1. Create the replacement credential **in the provider console** first.
2. Attach it to the account: `POST /api/v1/provider-accounts/{account_id}/credentials`
   (the secret is write-only; it is stored envelope-encrypted with a key version).
3. Verify it works: `POST /api/v1/provider-accounts/{account_id}/verify`, then
   send a test to an allowlisted address.
4. Revoke the old credential in the console and in the platform:
   `POST /api/v1/provider-accounts/{account_id}/credentials/{credential_id}/revoke`.
5. Confirm routing still shows the account eligible.

Rotating a credential **never** changes the account's quota — quota and rate
limits belong to the account, and adding keys does not create headroom
(SPEC.md invariant 3).

## 6. Encryption key rotation

`ENCRYPTION_KEY_VERSION` records which data key encrypted a credential. To rotate:
publish the new key under a new version, keep the old version readable, then
re-encrypt credentials by adding them under the new version and revoking the old
ones (section 5). Never delete the previous key version while any credential still
references it. The production key lives in an external KMS/secret manager
referenced by `ENCRYPTION_KEY_REF`, stored separately from backups (ADR 0004).

## 7. Retention and backup monitoring

**Retention** runs from the single-active scheduler every
`RETENTION_INTERVAL_SECONDS`; it can also be run by hand:

```bash
python -m app.workers.retention
```

It removes raw webhook payloads, staged uploads and per-row import outcomes past
their windows, and records deletions in
`email_platform_retention_deleted_total{dataset}`. Watch that the jobs actually
run (a flat counter with data past its window means the scheduler is not holding
the lock or is failing). Retention never deletes an audit or accounting fact —
the webhook row and its digest, the import summary and the campaign ledger stay.

**Backups**: alert on backup age and on failure, and periodically restore into an
isolated environment, then run the smoke test. Record the drill date and result;
a restore that has never been demonstrated is not a control (SPEC.md section 9).
