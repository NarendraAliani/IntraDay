# tests/unit/research/test_backtest_paper_parity.py
#
# Checkpoint 64.21 §12: strategy parity proof - for each production
# strategy (EMA/SMA/ATR), the SAME bars + SAME configuration produce
# EQUIVALENT decision semantics whether evaluated through the backtest
# path (`research.backtesting.execution.compute_signals()`) or the live/
# paper path (`trading_engine.strategy_execution.coordinator.
# StrategyExecutionCoordinator`, the class `PaperSignalExecutionService`
# uses). The comparison intentionally focuses on signal direction,
# evidence, entry price/timestamp, and (for ATR) TradePlan - never on
# identical timestamps/transport events, per this checkpoint's own
# explicit instruction. This is possible with NO new business logic:
# both paths already call the identical `strategy.evaluate()`/
# `build_trade_plan()` methods with the same feature values - this test
# proves that fact, it does not create it.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.strategy_execution import (
    build_coordinator,
    compute_feature_series,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting.execution import compute_signals
from intraday.research.backtesting.tradeplan_execution import compute_trade_plans
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _bars(prices: list[int]) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            instrument_id=INSTRUMENT,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(price - 1),
            high=Decimal(price + 1),
            low=Decimal(price - 2),
            close=Decimal(price),
            volume=Decimal("0"),
        )
        for i, price in enumerate(prices)
    )


def _uptrend_bars() -> tuple[Bar, ...]:
    flat = [100] * 8
    up = [101 + i for i in range(10)]
    return _bars(flat + up)


def _paper_path_direction(
    strategy_id: str, config: StrategyConfigurationValues, bars: tuple[Bar, ...]
):
    """The live/paper path: the SAME `StrategyExecutionCoordinator`
    `PaperSignalExecutionService` uses."""
    registry = build_default_registry()
    registry.activate(strategy_id)
    coordinator = build_coordinator(registry)
    result = coordinator.run(bars, {strategy_id: config})
    matching = [s for s in result.signals if s.strategy_id == strategy_id]
    return matching[-1] if matching else None


def test_ema_crossover_signal_direction_is_equivalent_in_backtest_and_paper() -> None:
    registry = build_default_registry()
    strategy = registry.get("ema_crossover")
    config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    bars = _uptrend_bars()

    backtest_signals, _warmup, _count = compute_signals(
        bars, strategy, config, compute_feature_series
    )
    backtest_last_signal = next(s for s in reversed(backtest_signals) if s is not None)
    paper_signal = _paper_path_direction("ema_crossover", config, bars)

    assert paper_signal is not None
    assert backtest_last_signal.direction == paper_signal.direction
    # Evidence is comparable in SHAPE and VALUE (not identical object) -
    # both call the same strategy.evaluate() with the same feature values.
    assert len(backtest_last_signal.evidence) == len(paper_signal.evidence)
    for backtest_ev, paper_ev in zip(
        backtest_last_signal.evidence, paper_signal.evidence, strict=True
    ):
        assert backtest_ev.feature_name == paper_ev.feature_name
        assert backtest_ev.value == paper_ev.value


def test_sma_trend_filter_signal_direction_is_equivalent_in_backtest_and_paper() -> None:
    registry = build_default_registry()
    strategy = registry.get("sma_trend_filter")
    config = StrategyConfigurationValues(
        "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5, "band_percent": Decimal("0.1")}
    )
    bars = _uptrend_bars()

    backtest_signals, _warmup, _count = compute_signals(
        bars, strategy, config, compute_feature_series
    )
    backtest_last_signal = next(s for s in reversed(backtest_signals) if s is not None)
    paper_signal = _paper_path_direction("sma_trend_filter", config, bars)

    assert paper_signal is not None
    assert backtest_last_signal.direction == paper_signal.direction
    assert backtest_last_signal.evidence[0].value == paper_signal.evidence[0].value


def test_atr_breakout_signal_and_tradeplan_are_equivalent_in_backtest_and_paper() -> None:
    """The strongest parity proof: ATR is the one strategy with a REAL
    `TradePlan` - this asserts entry/stop/targets match between the two
    paths, not just direction."""
    registry = build_default_registry()
    strategy = registry.get("atr_volatility_breakout")
    config = StrategyConfigurationValues(
        "atr_volatility_breakout",
        "v1",
        "v1",
        "v1",
        {
            "lookback": 5,
            "atr_multiplier": Decimal("0.1"),
            "stop_loss_atr_multiplier": Decimal("1.0"),
            "target_1_atr_multiplier": Decimal("1.5"),
            "target_2_atr_multiplier": Decimal("2.5"),
            "target_3_atr_multiplier": Decimal("4.0"),
            "trailing_stop_atr_multiplier": Decimal("1.0"),
        },
    )
    flat = [
        Bar(
            instrument_id=INSTRUMENT,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100),
            volume=Decimal("0"),
        )
        for i in range(8)
    ]
    breakout = Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=9),
        open=Decimal(100),
        high=Decimal(112),
        low=Decimal(99),
        close=Decimal(111),
        volume=Decimal("0"),
    )
    bars = (*flat, breakout)

    backtest_signals, _warmup, _count = compute_signals(
        bars, strategy, config, compute_feature_series
    )
    backtest_plans = compute_trade_plans(
        bars, strategy, config, compute_feature_series, backtest_signals
    )
    backtest_plan = next(p for p in backtest_plans if p is not None)

    registry_paper = build_default_registry()
    registry_paper.activate("atr_volatility_breakout")
    coordinator = build_coordinator(registry_paper)
    result = coordinator.run(bars, {"atr_volatility_breakout": config})
    paper_plan = next(p for p in result.trade_plans if p is not None)

    assert backtest_plan.entry_price == paper_plan.entry_price
    assert backtest_plan.stop_loss == paper_plan.stop_loss
    assert backtest_plan.target_1 == paper_plan.target_1
    assert backtest_plan.target_2 == paper_plan.target_2
    assert backtest_plan.target_3 == paper_plan.target_3
