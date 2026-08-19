# tests/unit/infrastructure/api/test_signal_pipeline_runtime.py
#
# Checkpoint 64.2: unit coverage for the ONE shared "closed bars ->
# promotion gate -> strategy/signal/risk/paper trigger" function -
# extracted from `market_data_ingestion_runtime.py` so the live
# WebSocket worker can reuse it (Checkpoint 64.1's own "single largest
# remaining gap"). `evaluate_bar_promotion()` and `run_active_loop_tick()`
# are monkeypatched here to isolate this module's own orchestration
# logic (grouping by instrument, chronological order, calling the
# active loop ONLY for a genuinely promoted bar) from either of those
# two ALREADY-real, ALREADY-tested functions' own internal behavior -
# never re-testing their logic here, only that this module calls them
# correctly.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarAggregationResult,
    BarQualityGrade,
    BarStatus,
)
from intraday.domain.market_data.promotion import PromotionResult
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api import signal_pipeline_runtime
from intraday.infrastructure.api.signal_pipeline_runtime import promote_bars_and_trigger_signals

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
NOW = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)  # a Monday, arbitrary session-neutral instant
SESSION = session_for_instant(NOW)


def _bar(
    instrument_id: InstrumentId, *, minute: int, status: BarStatus = BarStatus.CLOSED
) -> AggregatedBar:
    start = NOW + timedelta(minutes=minute)
    return AggregatedBar(
        instrument_id=instrument_id,
        timeframe=Timeframe.FIVE_MINUTE,
        interval_start=start,
        interval_end=start + timedelta(minutes=5),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=status,
        observation_count=5,
        data_source="test",
    )


def test_no_closed_bars_triggers_nothing() -> None:
    result = BarAggregationResult(bars=(), missing_intervals=(), anomalous_observations=())

    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )

    assert outcome.promoted_count == 0
    assert outcome.active_loop_invocations == 0


def test_a_forming_bar_is_never_promoted_or_triggered(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raises_if_called(**kwargs: object) -> None:
        raise AssertionError("evaluate_bar_promotion must not run for a non-CLOSED bar")

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _raises_if_called)
    result = BarAggregationResult(
        bars=(_bar(RELIANCE, minute=0, status=BarStatus.FORMING),),
        missing_intervals=(),
        anomalous_observations=(),
    )

    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )

    assert outcome.promoted_count == 0
    assert outcome.active_loop_invocations == 0


def test_a_sample_bar_never_triggers_the_active_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE trading-grade-bar gate itself - a closed bar that the REAL
    `evaluate_bar_promotion()` grades SAMPLE_BAR must never reach the
    strategy engine, no matter how healthy the connection looks."""

    def _fake_promotion(**kwargs: object) -> PromotionResult:
        from intraday.domain.market_data.promotion import PromotionCondition

        return PromotionResult(
            grade=BarQualityGrade.SAMPLE_BAR,
            failed_conditions=(PromotionCondition.CONNECTION_HEALTHY,),
            evaluated_at=NOW,
        )

    def _raises_if_called(**kwargs: object) -> None:
        raise AssertionError("run_active_loop_tick must not run for a SAMPLE_BAR")

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _fake_promotion)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _raises_if_called)
    result = BarAggregationResult(
        bars=(_bar(RELIANCE, minute=0),), missing_intervals=(), anomalous_observations=()
    )

    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )

    assert outcome.promoted_count == 0
    assert outcome.active_loop_invocations == 0


def test_a_trading_grade_bar_triggers_the_active_loop_with_full_bar_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=NOW
        )

    def _fake_active_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _fake_active_loop)

    bar_1 = _bar(RELIANCE, minute=0)
    bar_2 = _bar(RELIANCE, minute=5)
    result = BarAggregationResult(
        bars=(bar_1, bar_2), missing_intervals=(), anomalous_observations=()
    )

    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )

    assert outcome.promoted_count == 2
    assert outcome.active_loop_invocations == 2
    # The SECOND call must carry BOTH bars (warm-up history), not just
    # the one that was just promoted.
    assert len(calls[0]["bars"]) == 1  # type: ignore[arg-type]
    assert len(calls[1]["bars"]) == 2  # type: ignore[arg-type]
    assert calls[1]["instrument_id"] == RELIANCE


def test_each_instrument_gets_its_own_independent_bar_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=NOW
        )

    def _fake_active_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _fake_active_loop)

    result = BarAggregationResult(
        bars=(_bar(RELIANCE, minute=0), _bar(TCS, minute=0)),
        missing_intervals=(),
        anomalous_observations=(),
    )

    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )

    assert outcome.active_loop_invocations == 2
    instrument_ids = {call["instrument_id"] for call in calls}
    assert instrument_ids == {RELIANCE, TCS}
    # Neither instrument's history should have been contaminated by the other's.
    assert all(len(call["bars"]) == 1 for call in calls)  # type: ignore[arg-type]
