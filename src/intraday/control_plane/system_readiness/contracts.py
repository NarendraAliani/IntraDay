# src/intraday/control_plane/system_readiness/contracts.py
#
# Checkpoint 50 Rule 10: technology-neutral system-readiness vocabulary.
# Mirrors `control_plane/market_data_health/contracts.py`'s own shape
# exactly (state enum + frozen snapshot dataclass) - the ONE established
# pattern this project already uses for "classify observed facts into a
# named, evidence-backed state," reused rather than reinvented.
from __future__ import annotations

import enum
from dataclasses import dataclass


class SystemReadinessState(enum.Enum):
    """Deliberately not a copy of every individual subsystem's own
    vocabulary (`MarketDataHealthState`, `SessionStatus`,
    `TradingHaltStatus`) - this is the ONE composed, operator-facing
    answer to "can this platform be trusted right now?", each value
    covering a distinct class of "not fully trustworthy" reason."""

    READY = "READY"
    """Every checked signal is healthy and there is no unresolved
    safety event."""
    DEGRADED = "DEGRADED"
    """Not failed, but at least one signal is less than fully healthy
    (e.g. market data stale, or the market is simply closed right
    now) - orders should not be assumed safe without checking why."""
    HALTED = "HALTED"
    """The kill switch is engaged. Distinct from DEGRADED/FAILED
    because this is a deliberate, actor-initiated state, not a
    detected fault."""
    SQUARE_OFF_UNRESOLVED = "SQUARE_OFF_UNRESOLVED"
    """An `EmergencySquareOffEvent` exists that has not reached
    `COMPLETED` - `IN_PROGRESS`, `FAILED_RETRYABLE`, or
    `RECONCILIATION_REQUIRED`. The single most safety-critical state
    this evaluator can report: exposure may still be open."""
    FAILED = "FAILED"
    """A core infrastructure dependency (database) is unreachable -
    nothing else can be trusted until this is fixed."""


@dataclass(frozen=True, slots=True)
class SystemReadinessSnapshot:
    state: SystemReadinessState
    reasons: tuple[str, ...]
    """Always non-empty when `state is not READY` - every non-READY
    state must be explainable, never a bare status code with no
    evidence (this project's own "never claim HEALTHY without
    evidence" discipline, applied to the composed state too)."""
    database_ok: bool
    market_data_state: str
    session_status: str
    kill_switch_engaged: bool
    square_off_unresolved_count: int
