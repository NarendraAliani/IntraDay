# File: src/intraday/control_plane/audit/events.py
#
# Checkpoint 12: the first real code in control_plane/audit (previously
# an architecture placeholder — see control_plane/audit/README.md at the
# repo root). Defines the technology-neutral vocabulary for a
# control-plane audit event: the outcome enum and the read-side value
# object. Pure domain/bounded-context types — no Django, no persistence
# detail, no HTTP concept. `application/repositories` and
# `application/services` may depend on this module (Application ->
# bounded contexts -> domain layering, .importlinter contract #3);
# `infrastructure/persistence` implements the write/read paths using
# these types as its vocabulary.
#
# Scope (Checkpoint 12): only risk-configuration activation is audited.
# Universe/strategy-version activation intentionally remain unaudited
# this checkpoint (see taskReport.md) — this module's types are written
# generically enough (`resource_type`/`resource_id`, not
# `risk_configuration_id`) to extend to them later without a redesign,
# without building that generalization out now.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ActivationOutcome(str, Enum):
    """What actually happened as a result of an activation request. Must
    reflect reality, not merely "the request was accepted" — Checkpoint
    10 established that activating an already-active version is a no-op;
    this enum makes that distinction visible in the audit trail instead
    of recording a false state transition."""

    ACTIVATED = "activated"
    ALREADY_ACTIVE = "already_active"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Read-side representation of one durable audit record. Every field
    here answers one of the WHO/WHAT/WHICH RESOURCE/WHEN/RESULT
    questions the checkpoint brief specifies, or is `previous_version`
    (context: what changed *from*) — no speculative fields. See
    docs/architecture/AUDITABILITY.md for the field-by-field
    justification."""

    actor: str
    action: str
    resource_type: str
    resource_id: str
    version: str
    previous_version: str | None
    outcome: ActivationOutcome
    occurred_at: datetime
    request_id: str
