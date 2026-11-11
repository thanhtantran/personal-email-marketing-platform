# 0007. Open/click tracking default

- Status: Accepted
- Date: 2026-11-09
- Related: SPEC.md sections 7, 13; PRD.md section 5

## Context

Opens and clicks are privacy-sensitive and frequently misleading (privacy proxies, mail scanners).
Tracking endpoints also introduce user-controlled redirect/URL risk if not constrained.

## Decision

- **First-party open/click tracking is disabled by default** (`TRACKING_ENABLED=false`).
- Provider-reported open/click events (when a provider sends them) may still be ingested and shown,
  clearly labelled as provider-reported estimates, not proof of human engagement.
- The config flag and interface exist so tracking can be enabled deliberately after a privacy
  review. When enabled, tracking uses a first-party redirect/pixel with disclosure, no
  user-controlled destination, and configurable disablement.

## Consequences

- Analytics in Phase 1 default to queued/accepted/delivered/bounced/complained/unsubscribed/failed/
  unknown, which are provider-reported and not scanner-inflated.
- No tracking endpoints are exposed while disabled.

## Alternatives considered

- Enable tracking by default: rejected — privacy risk and metric distortion without a review.
- Remove tracking entirely: rejected — the SPEC allows it behind a flag and a future review.

## Revisit trigger

A completed privacy review for the jurisdictions served, or a provider/legal requirement.
