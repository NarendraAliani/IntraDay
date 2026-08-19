# File: src/intraday/control_plane/market_data_watchdog/evaluator.py
#
# Checkpoint 64.1: pure classification of `MarketDataWatchdogState` from
# raw observed facts - no I/O, mirrors `market_data_health/evaluator.py`
# and `system_readiness/evaluator.py`'s own established precedent
# exactly. The caller (the market-data worker / a future scheduled
# tick) is responsible for gathering the actual facts.
from __future__ import annotations

from datetime import datetime, timedelta

from intraday.control_plane.market_data_watchdog.contracts import (
    MarketDataWatchdogEvaluation,
    MarketDataWatchdogSnapshot,
    MarketDataWatchdogState,
)

# Dhan's own documented heartbeat cadence (verified directly against
# https://dhanhq.co/docs/v2/live-market-feed/, Checkpoint 64/64.1's own
# research): the server pings every 10s and closes the connection after
# 40s of client silence. 30s is chosen as the packet-staleness
# threshold - comfortably inside that 40s hard-close window, so a
# genuinely stalled feed is flagged BEFORE Dhan itself would have
# already dropped the connection, never after.
STALE_PACKET_AGE = timedelta(seconds=30)

# No single "correct" bar-closure cadence exists across every
# configured timeframe (1m through 1h) - 5 minutes is a deliberately
# generous DEFAULT for the shortest common timeframe (1m bars), not a
# claim this suits every configured universe. Callers running a coarser
# timeframe should pass a wider `stale_bar_age` explicitly rather than
# rely on this default being correct for their configuration.
DEFAULT_STALE_BAR_AGE = timedelta(minutes=5)

# `connection_state` values (from the infrastructure-layer WorkerState
# enum's own `.value` strings - control_plane must not import that
# enum directly, Contract 2 of `.importlinter`) that mean "not actually
# running right now."
_DISCONNECTED_CONNECTION_STATES = frozenset(
    {"STOPPED", "RECONNECTING", "STOPPING", "AUTH_FAILED", "TOKEN_EXPIRED"}
)
_FAILED_CONNECTION_STATES = frozenset({"FAILED"})

# `token_state` values (from TokenLifecycleState's own `.value` strings,
# same reasoning) that mean the worker must never claim to be healthy,
# regardless of what the socket itself is doing.
_UNUSABLE_TOKEN_STATES = frozenset(
    {"EXPIRED", "MALFORMED", "UNCONFIGURED", "AUTH_FAILURE", "OPERATOR_ACTION_REQUIRED"}
)


def evaluate_market_data_watchdog(
    snapshot: MarketDataWatchdogSnapshot,
    *,
    now: datetime,
    stale_bar_age: timedelta = DEFAULT_STALE_BAR_AGE,
) -> MarketDataWatchdogEvaluation:
    """Precedence (most to least severe) - matching this project's own
    "most specific/severe wins" pattern:

    1. Token unusable -> FAILED. A live/reconnecting socket over an
       unusable token is not a state anything downstream may trust.
    2. Connection state itself reports FAILED -> FAILED.
    3. Connection state reports a not-currently-running state
       (STOPPED/RECONNECTING/STOPPING/AUTH_FAILED/TOKEN_EXPIRED) ->
       DISCONNECTED.
    4. No packet has EVER arrived -> DISCONNECTED (never claim healthy
       for a worker that has never actually received data, even if its
       own state machine currently says RUNNING).
    5. The most recent packet is older than `STALE_PACKET_AGE` -> STALE
       - "the socket is alive but market data has stopped," the
       precise failure mode a bare process-alive check can never catch.
    6. No bar has EVER closed, or the most recent one is older than
       `stale_bar_age` -> DEGRADED - packets are flowing but the
       pipeline downstream of them is not producing fresh bars.
    7. Otherwise -> HEALTHY.
    """
    reasons: list[str] = []

    if snapshot.token_state in _UNUSABLE_TOKEN_STATES:
        reasons.append(f"token_state_unusable:{snapshot.token_state}")
        return _result(MarketDataWatchdogState.FAILED, reasons, snapshot, now)

    if snapshot.connection_state in _FAILED_CONNECTION_STATES:
        reasons.append(f"connection_state:{snapshot.connection_state}")
        return _result(MarketDataWatchdogState.FAILED, reasons, snapshot, now)

    if snapshot.connection_state in _DISCONNECTED_CONNECTION_STATES:
        reasons.append(f"connection_state:{snapshot.connection_state}")
        return _result(MarketDataWatchdogState.DISCONNECTED, reasons, snapshot, now)

    if snapshot.last_packet_at is None:
        reasons.append("no_packet_ever_received")
        return _result(MarketDataWatchdogState.DISCONNECTED, reasons, snapshot, now)

    packet_age = now - snapshot.last_packet_at
    if packet_age > STALE_PACKET_AGE:
        reasons.append(f"last_packet_age_seconds:{packet_age.total_seconds():.1f}")
        return _result(MarketDataWatchdogState.STALE, reasons, snapshot, now)

    if snapshot.last_bar_at is None:
        reasons.append("no_bar_ever_closed")
        return _result(MarketDataWatchdogState.DEGRADED, reasons, snapshot, now)

    bar_age = now - snapshot.last_bar_at
    if bar_age > stale_bar_age:
        reasons.append(f"last_bar_age_seconds:{bar_age.total_seconds():.1f}")
        return _result(MarketDataWatchdogState.DEGRADED, reasons, snapshot, now)

    if snapshot.consecutive_failures > 0:
        # Flowing data right now, but recent history had failures -
        # worth surfacing even inside an otherwise-HEALTHY result,
        # never silently dropped from the report.
        reasons.append(f"recent_consecutive_failures:{snapshot.consecutive_failures}")

    return _result(MarketDataWatchdogState.HEALTHY, reasons, snapshot, now)


def _result(
    state: MarketDataWatchdogState,
    reasons: list[str],
    snapshot: MarketDataWatchdogSnapshot,
    now: datetime,
) -> MarketDataWatchdogEvaluation:
    return MarketDataWatchdogEvaluation(
        state=state,
        reasons=tuple(reasons),
        last_packet_age_seconds=(
            (now - snapshot.last_packet_at).total_seconds()
            if snapshot.last_packet_at is not None
            else None
        ),
        last_bar_age_seconds=(
            (now - snapshot.last_bar_at).total_seconds()
            if snapshot.last_bar_at is not None
            else None
        ),
    )


__all__ = [
    "evaluate_market_data_watchdog",
    "STALE_PACKET_AGE",
    "DEFAULT_STALE_BAR_AGE",
]
