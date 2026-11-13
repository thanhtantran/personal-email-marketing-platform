# Architecture Decision Records

Consequential decisions are recorded here with context, decision, alternatives and a revisit
trigger (see IMPLEMENTATION_PLAN.md section 7). Update the affected section of PRD/SPEC/
ARCHITECTURE in the same change when a decision alters a contract or invariant.

| ID | Decision | Status |
|---|---|---|
| [0001](0001-auth-and-session-model.md) | Auth and session model | Accepted |
| [0002](0002-migration-tool.md) | Migration tool | Accepted |
| [0003](0003-object-storage.md) | Object storage | Accepted |
| [0004](0004-secret-encryption.md) | Secret envelope encryption | Accepted |
| [0005](0005-deployment-target.md) | Deployment target | Accepted |
| [0006](0006-first-provider-resend.md) | First provider adapter (Resend) | Accepted |
| [0007](0007-tracking-default-off.md) | Open/click tracking default | Accepted |
| [0008](0008-provider-gateway-routing.md) | Provider gateway: compliant capacity routing | Accepted |
| [0009](0009-webhook-intake-and-unsubscribe.md) | Webhook intake, event normalization and one-click unsubscribe | Accepted |

## Template

```markdown
# NNNN. Title

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD

## Context

## Decision

## Consequences

## Alternatives considered

## Revisit trigger
```
