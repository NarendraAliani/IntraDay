# control_plane/audit

## Responsibility

Immutable audit trail for signals, risk decisions, orders and AI-agent proposals (Rule 5.7).

**Checkpoint 12** implemented the first real code here:
`ActivationOutcome` and `AuditEvent` (the technology-neutral event
vocabulary), consumed by `application/repositories.AuditRepository` and
implemented concretely by `infrastructure/persistence`'s
`AuditLogEntry` model + `DjangoAuditRepository`. Scope so far:
risk-configuration activation only. See
[docs/architecture/AUDITABILITY.md](../../docs/architecture/AUDITABILITY.md)
for the full model (schema, append-only enforcement, transactional
coupling, retention policy).

## Depends On

domain, ai_agent/guardrails

## Must Not Depend On

Mutable business logic

