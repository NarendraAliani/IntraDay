# tests/unit/control_plane/system_readiness/test_evaluator.py
#
# Checkpoint 50 Rule 10: coverage for the pure composed-readiness
# classifier - every state and the documented precedence order between
# them (database > square-off unresolved > kill switch > market
# data/session degradation > READY).
from __future__ import annotations

from intraday.control_plane.market_data_health.contracts import MarketDataHealthState
from intraday.control_plane.system_readiness.contracts import SystemReadinessState
from intraday.control_plane.system_readiness.evaluator import evaluate_readiness
from intraday.domain.session.contracts import SessionStatus


def _evaluate(**overrides: object):  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "database_ok": True,
        "market_data_state": MarketDataHealthState.CONNECTED_FRESH,
        "session_status": SessionStatus.OPEN,
        "kill_switch_engaged": False,
        "square_off_unresolved_count": 0,
    }
    defaults.update(overrides)
    return evaluate_readiness(**defaults)  # type: ignore[arg-type]


def test_everything_healthy_is_ready() -> None:
    snapshot = _evaluate()
    assert snapshot.state is SystemReadinessState.READY
    assert snapshot.reasons == ()


def test_database_down_is_failed_and_outranks_everything_else() -> None:
    snapshot = _evaluate(
        database_ok=False,
        kill_switch_engaged=True,
        square_off_unresolved_count=3,
    )
    assert snapshot.state is SystemReadinessState.FAILED
    assert snapshot.reasons == ("database_unreachable",)


def test_unresolved_square_off_outranks_kill_switch() -> None:
    snapshot = _evaluate(kill_switch_engaged=True, square_off_unresolved_count=1)
    assert snapshot.state is SystemReadinessState.SQUARE_OFF_UNRESOLVED
    assert snapshot.reasons == ("emergency_square_off_unresolved:1",)


def test_kill_switch_engaged_with_no_unresolved_square_off_is_halted() -> None:
    snapshot = _evaluate(kill_switch_engaged=True)
    assert snapshot.state is SystemReadinessState.HALTED
    assert snapshot.reasons == ("kill_switch_engaged",)


def test_stale_market_data_is_degraded_not_failed() -> None:
    snapshot = _evaluate(market_data_state=MarketDataHealthState.CONNECTED_STALE)
    assert snapshot.state is SystemReadinessState.DEGRADED
    assert snapshot.reasons == ("market_data:CONNECTED_STALE",)


def test_market_closed_state_alone_is_degraded_not_failed() -> None:
    """MARKET_CLOSED market-data state is intentionally excluded from
    the degraded set (a closed market having no fresh quote is
    expected) - session_status not OPEN is what actually drives this
    one, and by itself is a legitimate, non-alarming DEGRADED reason,
    not READY (an operator should still be told trading is not
    currently possible)."""
    snapshot = _evaluate(
        market_data_state=MarketDataHealthState.MARKET_CLOSED,
        session_status=SessionStatus.CLOSED,
    )
    assert snapshot.state is SystemReadinessState.DEGRADED
    assert snapshot.reasons == ("session:CLOSED",)


def test_both_market_data_and_session_degraded_report_both_reasons() -> None:
    snapshot = _evaluate(
        market_data_state=MarketDataHealthState.ERROR,
        session_status=SessionStatus.HOLIDAY,
    )
    assert snapshot.state is SystemReadinessState.DEGRADED
    assert snapshot.reasons == ("market_data:ERROR", "session:HOLIDAY")


def test_snapshot_carries_the_raw_facts_regardless_of_state() -> None:
    snapshot = _evaluate(
        market_data_state=MarketDataHealthState.DISCONNECTED,
        session_status=SessionStatus.PRE_OPEN,
        square_off_unresolved_count=0,
    )
    assert snapshot.database_ok is True
    assert snapshot.market_data_state == "DISCONNECTED"
    assert snapshot.session_status == "PRE_OPEN"
    assert snapshot.kill_switch_engaged is False
    assert snapshot.square_off_unresolved_count == 0
