# Threat model (Phase 1, single-owner)

Established in Stage 0 and reviewed each stage. It covers the local/single-host Phase 1 deployment
and stays valid for the Stage 7 production profile.

## Assets

| Asset | Notes |
|---|---|
| Contact data (email, attributes, consent evidence) | Personal data; consent evidence is sensitive. |
| Suppression / unsubscribe state | Correctness is a safety and legal invariant. |
| Provider credentials | Secret; compromise enables sending as the operator. |
| Campaign content and snapshots | Integrity matters; tampering changes what is sent. |
| Session tokens | Bearer of owner authority. |
| Audit log | Evidence of administrative actions. |

## Actors and trust boundaries

- **Owner** (trusted operator) via browser and Google identity.
- **Recipients** (untrusted) via public unsubscribe and provider webhooks.
- **Provider** (semi-trusted) via signed webhooks and API responses.
- **Internet / anonymous attackers** (untrusted).

Trust boundaries: browser→API (session + CSRF), provider→API (webhook signature), API→provider
(outbound, credential-authenticated), worker↔database (tenant-scoped), object storage (signed URLs).

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Session theft (XSS) | HttpOnly/Secure/SameSite cookies, CSP, sanitized templates, no token in browser storage, server-side sessions with revocation. |
| CSRF on mutations | CSRF double-submit token for cookie-authenticated mutations. |
| OAuth mix-up / replay | state + nonce, PKCE, issuer/audience/signature/expiry validation, exact redirect allowlist, stable `sub`. |
| Non-owner access | Owner allowlist, fail closed; every query tenant-scoped from server-side membership. |
| Cross-tenant data access | `tenant_id` on every row, composite FKs, repository-scoped access, isolation tests (RLS later). |
| Credential disclosure | Envelope encryption, write-only secrets, redaction in logs/traces/errors. |
| Secret leakage to logs | No raw secrets or recipient PII in logs, metrics labels or URLs. |
| Webhook spoof / replay | Signature + timestamp verification, constant-time compare, `provider_event_id`/`svix-id` dedupe, bounded raw payload retention. |
| CSV formula injection | Escape leading `= + - @` on export; strict import limits and safe parsing. |
| Malicious template HTML | Allowlist sanitizer; no scripts, event handlers, iframes, unsafe URLs/protocols, or user-controlled endpoints. |
| SSRF via template URLs/assets | Restrict external embeds; validate/allowlist remote references. |
| Duplicate sends after timeout | `unknown` state, provider idempotency where available, reconciliation; no blind retry/failover. |
| Unsubscribe race | Recheck suppression immediately before each provider submit; bounding batch size. |
| Quota/policy evasion | No key/account rotation to bypass limits; stale/unknown capacity blocks routing. |
| Data over-retention | Configurable retention for raw imports, provider payloads, snapshots, events and backups. |

## Explicitly out of scope for Phase 1

Multi-tenant abuse response, public signup hardening, billing/PII for payment, and DDoS beyond a
reverse-proxy/node baseline are Phase 2 concerns and are listed in the Phase 2 work plan.
