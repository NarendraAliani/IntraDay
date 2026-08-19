# File: src/intraday/control_plane/market_data_watchdog/contracts.py
#
# Checkpoint 64.1: vocabulary for the continuous-worker watchdog - see
# package docstring for why this is separate from `market_data_health`.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class MarketDataWatchdogState(enum.Enum):
    """The explicit vocabulary Checkpoint 64.1's own brief asked for.
    HEALTHY is the only "everything is fine" state - every other state
    names a specific, distinguishable problem, matching
    `MarketDataHealthState`'s own established "never a generic red
    icon" discipline."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    """Packets are still arriving, but no new bar has closed within the
    expected window - the socket is alive but the pipeline downstream
    of it may not be keeping up."""
    STALE = "STALE"
    """No new packet has arrived within the expected window, but the
    connection has not been reported lost - the classic "silently
    stopped ticking" failure a socket-alive check alone can never
    catch."""
    DISCONNECTED = "DISCONNECTED"
    """The worker's own connection state machine reports a
    disconnected/reconnecting state."""
    FAILED = "FAILED"
    """The token is known unusable (EXPIRED/MALFORMED/UNCONFIGURED/
    AUTH_FAILURE/OPERATOR_ACTION_REQUIRED) or the worker's own state
    machine reports a terminal failure - the worst-case state,
    outranking everything else below it."""


@dataclass(frozen=True, slots=True)
class MarketDataWatchdogSnapshot:
    """Raw, already-observed facts the evaluator classifies - gathered
    by the caller (the worker process / a future scheduled tick) from
    already-existing state, never fetched by this module itself (pure,
    no I/O, matching every other evaluator in this bounded context)."""

    connection_state: str
    """A plain string, not the infrastructure-layer `WorkerState` enum
    directly - `control_plane` must not depend on `infrastructure`
    (Contract 2 of `.importlinter`); the caller passes `.value`."""
    token_state: str
    """Same reasoning - a plain string, the caller passes
    `TokenLifecycleState(...).value`."""
    last_packet_at: datetime | None
    last_valid_quote_at: datetime | None
    last_bar_at: datetime | None
    reconnect_count: int
    consecutive_failures: int


@dataclass(frozen=True, slots=True)
class MarketDataWatchdogEvaluation:
    state: MarketDataWatchdogState
    reasons: tuple[str, ...]
    """Never a bare state code alone - every non-HEALTHY state carries
    at least one specific, human-readable reason (Checkpoint 64.1's own
    "must produce actionable status" requirement)."""
    last_packet_age_seconds: float | None
    last_bar_age_seconds: float | None
