# ai_agent/guardrails

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Explicit boundary definitions of what AI agents must never bypass (Rule 5.7): risk engine, validation gates, deployment gates, auth, audit.

See `ai_agent/README.md` for the full AI Authority Model (Capability →
Governance/Approval → Trading Authority) clarified at Checkpoint 2. This
directory documents the *rules*; the governance gate itself is an action
(human/process approval), not a directory.

## Depends On

control_plane/audit, control_plane/kill_switch

## Must Not Depend On

Broker execution

