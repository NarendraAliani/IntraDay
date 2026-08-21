# tests/unit/research/test_tradeplan_execution.py
#
# Checkpoint 64.21 §5/§6/§7/§12/§14: coverage for the new TradePlan-based
# historical exit simulator - proves SL/T1/T2/T3/Trailing Stop
# simulation using the SAME semantic TradePlan values Paper Trading
# uses, a documented conservative intrabar ambiguity policy, and
# no-look-ahead protection for exits (not just entries).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting.tradeplan_execution import (
    ExitReason,
    compute_trade_plans,
    simulate_tradeplan_exit,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyDirection, TradePlan
from intraday.trading_engine.strategy_execution.registry import build_default_registry
from intraday.trading_engine.strategy_execution.strategies.atr_volatility_breakout import (
    AtrVolatilityBreakoutStrategy,
)

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _bar(*, minute: int, open_: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=minute),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("0"),
    )


def _plan(**overrides: object) -> TradePlan:
    defaults: dict[str, object] = dict(  # noqa: C408
        strategy_id="atr_volatility_breakout",
        code_version="v1",
        generated_at=BASE,
        calculation_method="test fixture",
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        target_1=Decimal("105"),
        target_2=Decimal("110"),
        target_3=Decimal("115"),
        trailing_stop_loss=None,
    )
    defaults.update(overrides)
    return TradePlan(**defaults)  # type: ignore[arg-type]


def test_stop_loss_exit_is_detected_on_the_first_bar_that_touches_it() -> None:
    plan = _plan()
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),  # entry bar
        _bar(minute=1, open_="99", high="100", low="98", close="99"),  # neither touched
        _bar(minute=2, open_="98", high="99", low="94", close="96"),  # stop touched (low<=95)
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_index == 2
    assert result.exit_reason is ExitReason.STOP_LOSS
    assert result.exit_price == Decimal("95")


def test_target_1_exit_is_detected_when_only_target_touched() -> None:
    plan = _plan()
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="100", high="106", low="99", close="105"),  # target_1 touched
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_reason is ExitReason.TARGET_1
    assert result.exit_price == Decimal("105")


def test_intrabar_ambiguity_stop_and_target_same_bar_assumes_stop_first() -> None:
    """§6: the mandatory, documented, conservative policy - a bar whose
    range covers BOTH the stop and a target must resolve to STOP_LOSS,
    never the favorable target outcome."""
    plan = _plan()
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        # This single bar's range [90, 120] covers stop_loss=95 AND
        # target_1..3 (105/110/115) simultaneously - a real, deliberately
        # ambiguous candle.
        _bar(minute=1, open_="100", high="120", low="90", close="100"),
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_reason is ExitReason.STOP_LOSS
    assert result.exit_price == Decimal("95")


def test_intrabar_ambiguity_multiple_targets_same_bar_assumes_nearest_target() -> None:
    """§6: a bar touching T1, T2, AND T3 must resolve to T1 (the nearest,
    conservative outcome), never assume price travelled all the way to
    T3 within one candle."""
    plan = _plan(stop_loss=None)  # isolate target-ordering behavior
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="100", high="120", low="99", close="118"),  # covers T1, T2, T3
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_reason is ExitReason.TARGET_1


def test_bearish_direction_uses_the_mirrored_touch_conditions() -> None:
    plan = _plan(stop_loss=Decimal("105"), target_1=Decimal("95"))
    # For a BEARISH trade, target is touched when bar.low <= target.
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="98", high="99", low="94", close="95"),
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BEARISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_reason is ExitReason.TARGET_1
    assert result.exit_price == Decimal("95")


def test_trailing_stop_exit_is_detected() -> None:
    plan = _plan(
        stop_loss=None,
        target_1=None,
        target_2=None,
        target_3=None,
        trailing_stop_loss=Decimal("97"),
    )
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="99", high="100", low="96", close="98"),
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is not None
    assert result.exit_reason is ExitReason.TRAILING_STOP
    assert result.exit_price == Decimal("97")


def test_no_exit_when_no_bar_ever_touches_a_level() -> None:
    """The caller is responsible for force-closing at EOD - the
    simulator honestly reports `None`, never fabricates an exit."""
    plan = _plan()
    bars = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="100", high="101", low="99", close="100"),
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is None


def test_the_entry_bars_own_range_never_determines_the_exit() -> None:
    """No-look-ahead for exits (§14): even if the ENTRY bar's own OHLC
    range would touch the stop/target, it must never be treated as the
    exit bar - matches the existing `test_entry_never_fills_at_the_
    signal_bars_own_price` discipline for entries."""
    plan = _plan()
    bars = (
        # Entry bar's own range covers the stop-loss (low=90) - must be
        # ignored; only bars AFTER entry_index are ever checked.
        _bar(minute=0, open_="100", high="101", low="90", close="100"),
        _bar(minute=1, open_="100", high="101", low="99", close="100"),
    )

    result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars
    )

    assert result is None


def test_future_bars_beyond_the_true_exit_never_change_the_result() -> None:
    """The look-ahead regression proof: truncating the bar series right
    after the true exit bar must produce the IDENTICAL exit - appending
    more bars afterward must never retroactively change an
    already-determined exit."""
    plan = _plan()
    bars_full = (
        _bar(minute=0, open_="100", high="101", low="99", close="100"),
        _bar(minute=1, open_="98", high="99", low="94", close="96"),  # stop touched here
        _bar(minute=2, open_="200", high="200", low="200", close="200"),  # irrelevant future bar
    )
    bars_truncated = bars_full[:2]

    full_result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars_full
    )
    truncated_result = simulate_tradeplan_exit(
        trade_plan=plan, direction=StrategyDirection.BULLISH, entry_index=0, bars=bars_truncated
    )

    assert full_result == truncated_result


def test_compute_trade_plans_reuses_the_strategys_own_build_trade_plan_method() -> None:
    """§2/§5: TradePlan construction is NOT duplicated for backtesting -
    this calls the real `AtrVolatilityBreakoutStrategy.build_trade_plan()`,
    the exact method the live coordinator also calls."""
    from intraday.application.services.strategy_execution import compute_feature_series
    from intraday.research.backtesting.execution import compute_signals
    from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

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
    flat = [_bar(minute=i, open_="100", high="101", low="99", close="100") for i in range(8)]
    breakout = _bar(minute=9, open_="100", high="112", low="99", close="111")
    bars = (*flat, breakout)

    signals, _warmup, _count = compute_signals(bars, strategy, config, compute_feature_series)
    plans = compute_trade_plans(bars, strategy, config, compute_feature_series, signals)

    assert len(plans) == len(bars)
    real_plan = plans[-1]
    assert real_plan is not None
    assert real_plan.stop_loss is not None
    assert real_plan.target_1 is not None


def test_compute_trade_plans_returns_none_for_a_directional_only_strategy() -> None:
    """`ema_crossover` has no `build_trade_plan` method at all - must
    never fabricate a plan for it."""
    from intraday.application.services.strategy_execution import compute_feature_series
    from intraday.research.backtesting.execution import compute_signals
    from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

    registry = build_default_registry()
    strategy = registry.get("ema_crossover")
    config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    bars = tuple(
        _bar(minute=i, open_=str(100 + i), high=str(101 + i), low=str(99 + i), close=str(100 + i))
        for i in range(20)
    )

    signals, _warmup, _count = compute_signals(bars, strategy, config, compute_feature_series)
    plans = compute_trade_plans(bars, strategy, config, compute_feature_series, signals)

    assert all(p is None for p in plans)


def test_atr_strategy_is_not_used_by_mistake() -> None:
    """Sanity: `AtrVolatilityBreakoutStrategy` really does have
    `build_trade_plan` - guards against the test above silently passing
    for the wrong reason."""
    assert hasattr(AtrVolatilityBreakoutStrategy(), "build_trade_plan")
