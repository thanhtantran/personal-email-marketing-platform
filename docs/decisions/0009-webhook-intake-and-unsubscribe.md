# 0009. Webhook intake, event normalization and one-click unsubscribe

- Status: Accepted
- Date: 2026-11-13
- Related: SPEC.md sections 7, 8, 10; IMPLEMENTATION_PLAN.md Stage 6

## Context

Providers report what happened to a message asynchronously, and those reports are the only
authoritative source for delivery, bounce and complaint. Three forces conflict:

- the reports are untrusted input (anyone can POST to a public URL),
- delivery is at-least-once and can arrive out of order, and
- the receiving side must never lose facts, never double-count them, and never let a forged
  report move suppression or analytics state.

Unsubscribe compounds this: it must be reachable in one action from every mailbox provider,
yet the link travels through the open internet and must not disclose recipient PII.

## Decision

- **Verify before persisting.** The webhook route is public and unauthenticated, so authenticity
  comes from the provider signature (and its timestamp) over the *raw* request body. A delivery
  that fails verification writes nothing. The route resolves the workspace from an unguessable
  `provider_accounts.webhook_public_id`, never from the request.
- **Accept durably, normalize asynchronously.** A verified delivery is written as one
  `webhook_events` row under `UNIQUE(provider_account_id, provider_event_id)` and queued through
  the transactional outbox. The raw body is retained out-of-band (TTL-bound, see
  `raw_webhook_retention_days`) and only its digest stays in the database, so the database never
  accumulates provider PII. If the body cannot be retained the request fails closed (503) so the
  provider's own retry becomes the recovery.
- **Replay is a no-op.** The unique constraint collapses a redelivered event onto the existing
  row; a duplicate acceptance returns success without enqueuing a second processing job, so a
  replayed or forged webhook cannot move analytics or suppression a second time.
- **Normalized events are append-only and deduplicated.** The worker re-normalizes the retained
  payload into `message_events`, keyed per tenant by `UNIQUE(tenant_id, event_key)`. The key is
  the provider event id when present, otherwise a digest over the canonical event fields (the
  address is folded into the digest, never stored in the key).
- **The ledger reducer is monotonic.** A failure is definitive, an acceptance marks an unresolved
  recipient accepted, `unknown` only marks an otherwise-unresolved recipient, and every later
  authoritative event resolves it. Weak signals (open, click, complaint) never rewrite a
  confirmed delivery, and events may arrive in any order without regressing state.
- **Acceptance is never conflated with delivery.** Analytics reads the recipient ledger for
  current state and `message_events` for provider-reported totals: `accepted` is a provider
  acceptance, `delivered` counts distinct delivered events, and an unresolved recipient stays
  `unknown`. Every response carries caveats explaining exactly that.
- **Suppression is one idempotent helper.** Complaint, hard bounce, unsubscribe and the manual
  endpoint all funnel through one upsert, so a duplicate webhook, a replayed link and a retried
  worker converge on one suppression and never reset its original occurrence time.
- **One-click unsubscribe is signed and PII-free.** The link is an HMAC over opaque ids
  (workspace, recipient, contact, campaign) and never contains an address. `GET` shows a
  confirmation page (mailbox scanners issue GETs); `POST` performs the unsubscribe, which is what
  the `List-Unsubscribe-Post` header targets. The suppression takes effect before the next
  dispatch eligibility check.

## Consequences

- A forged or replayed webhook is inert: it is rejected before persistence or collapsed by a
  unique constraint afterwards, and neither path reaches analytics or suppression.
- The dashboard can always distinguish provider acceptance from provider-reported delivery and
  can report `unknown` without inventing an outcome.
- Raw provider payloads are bounded and TTL-managed rather than kept in the database.
- Provider event names live only in the adapter layer; the reducer, analytics and suppression
  policy agree on one normalized vocabulary.

## Alternatives considered

- **Normalize inside the request.** Rejected: it couples the provider's latency and retry to our
  parsing and storage, and a slow or failing normalization would make the provider retry a
  delivery we already accepted.
- **Trust a shared secret in the query string instead of a signature.** Rejected: it is
  discoverable in logs and proxies, and it cannot detect a tampered body.
- **Unsubscribe on `GET`.** Rejected: link prefetchers and security scanners would unsubscribe
  recipients who never clicked, and a bot could enumerate the endpoint.
- **Store only the current recipient status.** Rejected: out-of-order and late events would be
  lost, and `unknown` could never be resolved by a later authoritative report.

## Revisit trigger

A provider whose webhooks are unsigned, or that cannot resend a delivery we failed to retain;
or a compliance requirement that changes the retention window or the unsubscribe link contract.
