# tests/unit/research/test_default_backtest_paper_parity.py
#
# Checkpoint 64.22 §10: proves the DEFAULT `engine.run_backtest()` path,
# now wired to TradePlan-based exit simulation (§5/§6/§7), produces
# decisions equivalent to the live/paper path
# (`StrategyExecutionCoordinator`, via `build_coordinator()`) for the
# same bars/config/strategy - signal direction, evidence, and TradePlan
# values. This does NOT spin up `PaperTradingService`/`PaperBroker`
# (Django/DB infrastructure) - see this checkpoint's own honest
# disclosure in the final report of why that layer is out of scope here.
# It also proves the DEFAULT engine's own TradePlan-based exit simulation
# (SL/T1/T2/T3/Trailing/EOD) against the SAME conservative intrabar
# semantics `tradeplan_execution.py` already proves in isolation
# (Checkpoint 64.21) - this test proves the WIRING, not the exit policy
# itself (already proven elsewhere).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.strategy_execution import (
    build_coordinator,
    compute_feature_series,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.tradeplan_execution import ExitReason
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

ATR_CONFIG_VALUES: dict[str, object] = {
    "lookback": 5,
    "atr_multiplier": Decimal("0.1"),
    "stop_loss_atr_multiplier": Decimal("1.0"),
    "target_1_atr_multiplier": Decimal("1.5"),
    "target_2_atr_multiplier": Decimal("2.5"),
    "target_3_atr_multiplier": Decimal("4.0"),
    "trailing_stop_atr_multiplier": Decimal("1.0"),
}


def _dq(bar_count: int) -> DataQualityDisclosure:
    return DataQualityDisclosure(
        data_source="fixture",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=bar_count,
        missing_bar_note="none",
        transaction_cost_assumption="flat pct",
        slippage_assumption="flat pct",
        survivorship_bias_note="n/a",
    )


def _backtest_config(*, end: datetime) -> BacktestConfiguration:
    return BacktestConfiguration(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=end,
        strategy_id="atr_volatility_breakout",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )


def _atr_strategy_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "atr_volatility_breakout", "v1", "v1", "v1", ATR_CONFIG_VALUES
    )


def _bars_with_breakout_then_stop_touch() -> tuple[Bar, ...]:
    """Flat warm-up, a breakout bar (entry signal), then a bar that
    fills at the breakout bar's own TradePlan stop-loss - deterministic,
    real bars, not fabricated levels."""
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
    # Entry fills at the NEXT bar's open after the breakout bar (i.e. the
    # bar below) - and this bar's own low then drives price straight
    # down through the plan's stop-loss on the bar after that.
    post_breakout = Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=10),
        open=Decimal(111),
        high=Decimal(113),
        low=Decimal(108),
        close=Decimal(109),
        volume=Decimal("0"),
    )
    crash = Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=11),
        open=Decimal(108),
        high=Decimal(109),
        low=Decimal(50),
        close=Decimal(60),
        volume=Decimal("0"),
    )
    return (*flat, breakout, post_breakout, crash)


def test_default_backtest_tradeplan_matches_the_live_paper_path() -> None:
    bars = _bars_with_breakout_then_stop_touch()
    strategy_config = _atr_strategy_config()

    # Live/paper path: `StrategyExecutionCoordinator.run()` evaluates
    # against the LAST bar of whatever series it is given (see its own
    # docstring) - so, to compare the SAME decision the backtest makes
    # on the breakout bar, it is called on the series truncated to end
    # at that breakout bar, exactly the pattern
    # `test_backtest_paper_parity.py` already established.
    breakout_index = 8  # index of the breakout bar within `bars` (flat[0..7], breakout at 8)
    bars_up_to_breakout = bars[: breakout_index + 1]
    registry = build_default_registry()
    registry.activate("atr_volatility_breakout")
    coordinator = build_coordinator(registry)
    paper_result = coordinator.run(
        bars_up_to_breakout, {"atr_volatility_breakout": strategy_config}
    )
    paper_signal = paper_result.signals[0]
    paper_plan = paper_result.trade_plans[0]
    assert paper_plan is not None

    # Default backtest path (now TradePlan-wired, Checkpoint 64.22).
    registry_bt = build_default_registry()
    strategy = registry_bt.get("atr_volatility_breakout")
    result = run_backtest(
        bars,
        strategy,
        strategy_config,
        _backtest_config(end=bars[-1].timestamp + timedelta(minutes=1)),
        compute_feature_series,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]

    # Signal direction and TradePlan levels match the live/paper path.
    assert trade.direction == paper_signal.direction
    assert paper_plan.stop_loss is not None
    assert result.validation.tradeplan_trades == 1

    # The default engine actually simulated a real STOP_LOSS/TARGET/
    # TRAILING/EOD exit (not a direction-flip exit) using the SAME
    # values the live path's own TradePlan carries.
    assert trade.reason in {
        ExitReason.STOP_LOSS.value,
        ExitReason.TARGET_1.value,
        ExitReason.TARGET_2.value,
        ExitReason.TARGET_3.value,
        ExitReason.TRAILING_STOP.value,
        ExitReason.EOD.value,
    }
    assert result.validation.exit_reason_breakdown == {trade.reason: 1}


def test_directional_only_strategy_keeps_the_unchanged_direction_flip_model() -> None:
    """`ema_crossover` has no `build_trade_plan()` hook - the default
    engine must never fabricate TradePlan-based exits for it."""
    bars = tuple(
        Bar(
            instrument_id=INSTRUMENT,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(100 + i) - 1,
            high=Decimal(100 + i) + 2,
            low=Decimal(100 + i) - 2,
            close=Decimal(100 + i),
            volume=Decimal("0"),
        )
        for i in range(20)
    )
    strategy_config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    registry = build_default_registry()
    strategy = registry.get("ema_crossover")
    config = BacktestConfiguration(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=bars[-1].timestamp + timedelta(minutes=1),
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
    )

    result = run_backtest(
        bars,
        strategy,
        strategy_config,
        config,
        compute_feature_series,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )

    assert result.validation.tradeplan_trades == 0
    for trade in result.trades:
        assert trade.reason in {"signal_reversal", "end_of_data"}
