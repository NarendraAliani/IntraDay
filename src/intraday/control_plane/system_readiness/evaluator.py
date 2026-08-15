# src/intraday/control_plane/system_readiness/evaluator.py
#
# Checkpoint 50 Rule 10: pure classification of `SystemReadinessState`
# from raw observed facts - no I/O, mirrors
# `control_plane/market_data_health/evaluator.py`'s own precedent
# exactly. The caller (infrastructure/api) is responsible for gathering
# the actual facts from each subsystem's own already-existing,
# already-tested repository/service.
from __future__ import annotations

from intraday.control_plane.market_data_health.contracts import MarketDataHealthState
from intraday.control_plane.system_readiness.contracts import (
    SystemReadinessSnapshot,
    SystemReadinessState,
)
from intraday.domain.session.contracts import SessionStatus

# States that mean "market data is not usably fresh right now" -
# MARKET_CLOSED is intentionally EXCLUDED: a closed market having no
# fresh quote is expected and correct, not a degradation.
_MARKET_DATA_DEGRADED_STATES = frozenset(
    {
        MarketDataHealthState.CONNECTED_STALE,
        MarketDataHealthState.DISCONNECTED,
        MarketDataHealthState.AUTHENTICATION_FAILED,
        MarketDataHealthState.ERROR,
    }
)


def evaluate_readiness(
    *,
    database_ok: bool,
    market_data_state: MarketDataHealthState,
    session_status: SessionStatus,
    kill_switch_engaged: bool,
    square_off_unresolved_count: int,
) -> SystemReadinessSnapshot:
    """Precedence (most to least severe) - matching this project's own
    "most specific/severe wins" pattern from
    `market_data_health.evaluator.evaluate_health()`:

    1. Database unreachable -> FAILED. Nothing above this layer can be
       trusted at all.
    2. An `EmergencySquareOffEvent` is unresolved -> SQUARE_OFF_UNRESOLVED.
       Exposure may genuinely still be open; this outranks even the kill
       switch's own HALTED state because it is the more specific,
       more urgent fact.
    3. Kill switch engaged (with square-off already resolved, or none
       ever needed) -> HALTED.
    4. Market data degraded (stale/disconnected/error/auth-failed) OR
       the market is simply not open right now -> DEGRADED.
    5. Otherwise -> READY.
    """
    reasons: list[str] = []

    if not database_ok:
        reasons.append("database_unreachable")
        return SystemReadinessSnapshot(
            state=SystemReadinessState.FAILED,
            reasons=tuple(reasons),
            database_ok=database_ok,
            market_data_state=market_data_state.value,
            session_status=session_status.value,
            kill_switch_engaged=kill_switch_engaged,
            square_off_unresolved_count=square_off_unresolved_count,
        )

    if square_off_unresolved_count > 0:
        reasons.append(f"emergency_square_off_unresolved:{square_off_unresolved_count}")
        return SystemReadinessSnapshot(
            state=SystemReadinessState.SQUARE_OFF_UNRESOLVED,
            reasons=tuple(reasons),
            database_ok=database_ok,
            market_data_state=market_data_state.value,
            session_status=session_status.value,
            kill_switch_engaged=kill_switch_engaged,
            square_off_unresolved_count=square_off_unresolved_count,
        )

    if kill_switch_engaged:
        reasons.append("kill_switch_engaged")
        return SystemReadinessSnapshot(
            state=SystemReadinessState.HALTED,
            reasons=tuple(reasons),
            database_ok=database_ok,
            market_data_state=market_data_state.value,
            session_status=session_status.value,
            kill_switch_engaged=kill_switch_engaged,
            square_off_unresolved_count=square_off_unresolved_count,
        )

    if market_data_state in _MARKET_DATA_DEGRADED_STATES:
        reasons.append(f"market_data:{market_data_state.value}")
    if session_status is not SessionStatus.OPEN:
        reasons.append(f"session:{session_status.value}")

    state = SystemReadinessState.DEGRADED if reasons else SystemReadinessState.READY
    return SystemReadinessSnapshot(
        state=state,
        reasons=tuple(reasons),
        database_ok=database_ok,
        market_data_state=market_data_state.value,
        session_status=session_status.value,
        kill_switch_engaged=kill_switch_engaged,
        square_off_unresolved_count=square_off_unresolved_count,
    )
