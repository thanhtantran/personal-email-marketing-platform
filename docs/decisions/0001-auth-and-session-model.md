# 0001. Auth and session model

- Status: Accepted
- Date: 2026-11-09
- Related: SPEC.md section 8, ARCHITECTURE.md section 2

## Context

The web UI (Next.js) and the API (FastAPI) are separate processes. The operator signs in with
Google. Phase 1 permits exactly one owner. We must prevent token theft via XSS, support server-side
revocation, and keep tenant context out of client-controlled input.

## Decision

- Google OIDC **Authorization Code flow with PKCE**, handled by the API at `/api/v1/auth/google/*`.
- On callback validate issuer, audience, state, nonce, signature and expiry; reject any mismatch.
- Internal user is keyed by the stable provider subject (`google_subject`), never by email alone.
- Enforce an **owner allowlist** from deployment configuration (`OWNER_GOOGLE_SUB` preferred);
  any other identity fails closed. Do not rely on obscurity of a signup URL.
- Sessions are **opaque server-side tokens**: a random token is issued to the browser; only its
  hash (`sessions.token_hash`) is stored. Cookie flags: `Secure`, `HttpOnly`, `SameSite=Lax`,
  short idle/absolute expiry, rotated after login, revoked on logout.
- **Tenant context** is resolved server-side from the active membership for the session user and
  is never accepted as trusted request input.
- Cookie-authenticated mutations require a **CSRF double-submit token**.
- No access/refresh token is stored in browser storage.

## Consequences

- A per-request session lookup is required (database now, optionally cached in Redis later).
- Revocation and session rotation are straightforward.
- The UI must route authentication through the API rather than managing tokens client-side.

## Alternatives considered

- JWT access token in `localStorage`: rejected — XSS exposure and hard revocation.
- Next.js BFF holding provider tokens: rejected for Phase 1 — adds a token-handling surface without
  removing the need for server-side sessions.

## Revisit trigger

Phase 2 multi-user roles, or the addition of native/mobile clients that change the session model.
