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


def test_on_instrument_progress_is_called_once_per_instrument_with_running_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 64.18 §5: the ONE injection point scanner-progress
    writers use - `None` by default (every pre-existing caller,
    including the REST-ingestion path, is unaffected)."""

    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=NOW
        )

    def _fake_active_loop(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _fake_active_loop)

    result = BarAggregationResult(
        bars=(_bar(RELIANCE, minute=0), _bar(TCS, minute=0)),
        missing_intervals=(),
        anomalous_observations=(),
    )
    progress_calls: list[tuple[str, int, int]] = []

    promote_bars_and_trigger_signals(
        result,
        session=SESSION,
        clock=NOW,
        connection_is_healthy=True,
        on_instrument_progress=lambda instrument_id, processed, total: progress_calls.append(
            (instrument_id, processed, total)
        ),
    )

    assert len(progress_calls) == 2
    processed_counts = [call[1] for call in progress_calls]
    assert processed_counts == [1, 2]  # running total, never reset mid-loop
    totals = {call[2] for call in progress_calls}
    assert totals == {2}  # universe_total is constant across the whole call


def test_on_instrument_progress_defaults_to_none_and_is_never_called_unless_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=NOW
        )

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", lambda **kwargs: None)

    result = BarAggregationResult(
        bars=(_bar(RELIANCE, minute=0),), missing_intervals=(), anomalous_observations=()
    )

    # Must not raise even though no callback was supplied.
    outcome = promote_bars_and_trigger_signals(
        result, session=SESSION, clock=NOW, connection_is_healthy=True
    )
    assert outcome.promoted_count == 1


# ---------------------------------------------------------------------------
# CHECKPOINT 78 regression: the exact gap CHECKPOINT_77 found - this
# module used to construct `StrategyConfigurationValues(strategy_id,
# "v1", "v1", "v1", {})`, an EMPTY values dict, for every strategy,
# every tick. No existing test caught this because every other test in
# this file (above) fakes `run_active_loop_tick` entirely, and
# `test_active_loop_end_to_end.py`'s own `_config()` helper always
# supplies real values directly - neither exercises what THIS module
# itself actually constructs. These 2 tests close that gap: the first
# proves this module's own construction site now produces real,
# non-empty values (in isolation, matching every other test in this
# file's own "fake run_active_loop_tick, inspect what was passed"
# style); the second goes one level deeper and lets the REAL
# `run_active_loop_tick` -> coordinator -> `strategy.evaluate()` chain
# run, confirming a real, non-`None` `config.values` dict genuinely
# reaches the strategy - not just this module's own local variable.
# ---------------------------------------------------------------------------


def test_checkpoint_78_configuration_values_are_no_longer_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct regression for the exact construction site the bug was
    in: for all 3 registered strategies, the `configuration` kwarg this
    module passes to `run_active_loop_tick` must carry REAL values from
    that strategy's own schema defaults, never an empty dict."""
    calls: list[dict[str, object]] = []

    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=NOW
        )

    def _fake_active_loop(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)
    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _fake_active_loop)

    expected_keys = {
        "ema_crossover": {"fast_lookback", "slow_lookback"},
        "sma_trend_filter": {"lookback", "band_percent"},
        "atr_volatility_breakout": {
            "lookback",
            "atr_multiplier",
            "stop_loss_atr_multiplier",
            "target_1_atr_multiplier",
            "target_2_atr_multiplier",
            "target_3_atr_multiplier",
            "trailing_stop_atr_multiplier",
        },
    }
    for strategy_id, keys in expected_keys.items():
        calls.clear()
        result = BarAggregationResult(
            bars=(_bar(RELIANCE, minute=0),), missing_intervals=(), anomalous_observations=()
        )
        promote_bars_and_trigger_signals(
            result, session=SESSION, clock=NOW, connection_is_healthy=True, strategy_id=strategy_id
        )
        assert len(calls) == 1
        configuration = calls[0]["configuration"]
        assert configuration.values != {}, f"{strategy_id}: configuration.values is still empty"
        assert set(configuration.values.keys()) == keys
        # Real Decimal/int values, never None/placeholder - and every
        # DECIMAL-typed parameter is a REAL `Decimal` instance, not a
        # bare float/str, matching `require_decimal()`'s own strict
        # `isinstance` check (a second, real gap CHECKPOINT_78's own
        # verification found and fixed alongside the empty-dict one -
        # `default_configuration_values()` alone returns plain Python
        # literals; `coerce_configuration_values()` is what turns them
        # into real `Decimal`s).
        for parameter_id, value in configuration.values.items():
            assert value is not None
            if isinstance(value, float):
                pytest.fail(
                    f"{strategy_id}.{parameter_id} is a bare float ({value!r}), not a "
                    "Decimal - require_decimal() would reject this"
                )


def test_checkpoint_78_decimal_typed_strategies_pass_real_decimal_defaults() -> None:
    """Direct regression for the SECOND gap CHECKPOINT_78's own
    verification found: `default_configuration_values()` alone returns
    a `ParameterDefinition.default` VERBATIM (a plain Python literal,
    e.g. `2.0`), never a `Decimal` - `require_decimal()`
    (`trading_engine.strategy_execution.contracts`) does a strict
    `isinstance(value, Decimal)` check that a bare float fails.
    `sma_trend_filter`/`atr_volatility_breakout` are both DECIMAL-typed
    and would have raised `InvalidParameterValueError` from their own
    `evaluate()` without `coerce_configuration_values()` applied too."""
    from decimal import Decimal as DecimalType

    from intraday.infrastructure.api.signal_pipeline_runtime import _configuration_values_for

    for strategy_id, decimal_keys in (
        ("sma_trend_filter", ("band_percent",)),
        (
            "atr_volatility_breakout",
            (
                "atr_multiplier",
                "stop_loss_atr_multiplier",
                "target_1_atr_multiplier",
                "target_2_atr_multiplier",
                "target_3_atr_multiplier",
                "trailing_stop_atr_multiplier",
            ),
        ),
    ):
        values = _configuration_values_for(strategy_id)
        for key in decimal_keys:
            assert isinstance(values[key], DecimalType), (
                f"{strategy_id}.{key} is {type(values[key]).__name__!r}, not Decimal - "
                "require_decimal() would reject this"
            )


@pytest.mark.django_db
def test_checkpoint_78_real_evaluate_receives_non_empty_config_never_a_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deeper regression: does NOT fake `run_active_loop_tick` -
    lets the REAL chain (`run_active_loop_tick` -> `PaperSignalExecutionService`
    -> `StrategyExecutionCoordinator.run()` -> `strategy.evaluate()`)
    execute, and spies on `EmaCrossoverStrategy.evaluate` itself (the
    real, registered strategy instance's own bound method) to prove the
    `config` argument it receives has a real, non-empty `.values` dict
    - and that calling it does not raise (the original bug's exact
    failure mode: `require_int(config.values, "fast_lookback")` raising
    `KeyError` on an empty dict, silently swallowed by the coordinator's
    own isolation boundary as a `StrategyExecutionFailure` - this test
    would have failed on the original construction, by design)."""
    from intraday.domain.session.calendar import session_for_instant
    from intraday.trading_engine.strategy_execution.strategies.ema_crossover import (
        EmaCrossoverStrategy,
    )

    # A genuinely mid-session, real-trading-day instant - unlike the
    # module-level `NOW`/`SESSION` (deliberately "session-neutral" per
    # their own comment, fine for every OTHER test in this file, all of
    # which fake `run_active_loop_tick` and never reach its own real
    # session-open gate) - this test lets that gate run for real, so it
    # needs a real open-market instant. 2026-08-03 is CAS_EFFECTIVE_DATE
    # itself, already independently confirmed a real trading day by
    # multiple checkpoints this session.
    live_now = datetime(2026, 8, 3, 5, 0, 0, tzinfo=UTC)
    live_session = session_for_instant(live_now)

    captured: list[object] = []
    real_evaluate = EmaCrossoverStrategy.evaluate

    def _spy_evaluate(self, bar, feature_values, config):  # noqa: ANN001
        captured.append(config)
        return real_evaluate(self, bar, feature_values, config)

    monkeypatch.setattr(EmaCrossoverStrategy, "evaluate", _spy_evaluate)

    def _always_promotes(**kwargs: object) -> PromotionResult:
        return PromotionResult(
            grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=live_now
        )

    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)

    live_bar = AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        interval_start=live_now,
        interval_end=live_now + timedelta(minutes=5),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=BarStatus.CLOSED,
        observation_count=5,
        data_source="test",
    )
    result = BarAggregationResult(
        bars=(live_bar,), missing_intervals=(), anomalous_observations=()
    )

    # Must not raise - the original bug's KeyError was caught by the
    # coordinator's own isolation boundary, so a raw crash here would
    # actually indicate something NEW and worse, not the original bug
    # resurfacing identically - but a passing call combined with the
    # assertions below is the real proof this specific gap is closed.
    promote_bars_and_trigger_signals(
        result,
        session=live_session,
        clock=live_now,
        connection_is_healthy=True,
        strategy_id="ema_crossover",
    )

    assert len(captured) == 1, "EmaCrossoverStrategy.evaluate was never reached"
    real_config = captured[0]
    assert real_config.values != {}, "evaluate() still received an empty values dict"
    assert real_config.values.get("fast_lookback") == 12
    assert real_config.values.get("slow_lookback") == 26
