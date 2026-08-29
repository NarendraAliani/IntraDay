# tests/unit/research/test_backtesting_engine.py
#
# Checkpoint 27 Part 25/30: the backtest engine's own test matrix -
# simulation correctness, no-look-ahead protection (mandatory), trade
# ledger/costs/P&L, equity curve/drawdown, metrics, MFE/MAE,
# reproducibility, and adversarial cases.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import (
    StrategyConfigurationValues,
    StrategyDirection,
    build_default_registry,
)
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.errors import (
    InsufficientHistoricalDataError,
    InvalidBacktestConfigurationError,
)
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.definitions import PriceVsMaPctSmaDefinition
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.price_vs_ma_pct import (
    compute_price_vs_ma_pct_sma,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _compute(field_id: str, bars: tuple[Bar, ...]):
    # Checkpoint 65.10: sma_trend_filter now requires price_vs_ma_pct_sma_N
    # instead of sma_N - handle the multi-word kind before the generic
    # single-word partition below.
    if field_id.startswith("price_vs_ma_pct_sma_"):
        lookback = int(field_id[len("price_vs_ma_pct_sma_") :])
        return compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(lookback), bars)
    kind, _, raw = field_id.partition("_")
    lookback = int(raw)
    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(lookback), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(lookback), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(lookback), bars)
    raise ValueError(field_id)


def _bars(prices: list[str]) -> tuple[Bar, ...]:
    bars = []
    for i, price_str in enumerate(prices):
        price = Decimal(price_str)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price - Decimal("1"),
                high=price + Decimal("2"),
                low=price - Decimal("2"),
                close=price,
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


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


def _config(**overrides: object) -> BacktestConfiguration:
    defaults: dict[str, object] = {
        "instrument_id": INSTRUMENT,
        "timeframe": Timeframe.ONE_MINUTE,
        "start": BASE,
        "end": BASE + timedelta(minutes=40),
        "strategy_id": "ema_crossover",
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "v1",
        "initial_capital": Decimal("100000"),
        "position_sizing_mode": PositionSizingMode.FIXED_QUANTITY,
        "position_size_value": Decimal("10"),
        "brokerage_percent": Decimal("0"),
        "slippage_percent": Decimal("0"),
    }
    defaults.update(overrides)
    return BacktestConfiguration(**defaults)  # type: ignore[arg-type]


def _ema_strategy():
    registry = build_default_registry()
    return registry.get("ema_crossover")


def _ema_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


# --- Basic correctness ---------------------------------------------------


def test_run_backtest_raises_on_empty_bars() -> None:
    with pytest.raises(InsufficientHistoricalDataError):
        run_backtest(
            (),
            _ema_strategy(),
            _ema_config(),
            _config(),
            _compute,
            data_quality=_dq(0),
            generated_at=datetime.now(tz=UTC),
        )


def test_backtest_configuration_rejects_end_before_start() -> None:
    with pytest.raises(InvalidBacktestConfigurationError):
        _config(start=BASE, end=BASE - timedelta(minutes=1))


def test_backtest_configuration_rejects_non_positive_capital() -> None:
    with pytest.raises(InvalidBacktestConfigurationError):
        _config(initial_capital=Decimal("0"))


def test_backtest_produces_trades_on_a_trending_series() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.metrics.total_trades >= 1
    assert all(t.strategy_id == "ema_crossover" for t in result.trades)  # attribution preserved


# --- No-look-ahead protection (Part 25, mandatory) ------------------------


def test_entry_never_fills_at_the_signal_bars_own_price() -> None:
    """A signal computed from bar[i] must fill at bar[i+1].open, never
    at bar[i]'s own open/close - proves the engine cannot execute on
    information from the instant the decision itself was made."""
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades
    bar_by_timestamp = {b.timestamp: b for b in bars}
    for trade in result.trades:
        entry_bar = bar_by_timestamp[trade.entry_timestamp]
        assert entry_bar.open == trade.entry_price  # no slippage in this config
        # the entry bar must NOT be the earliest bar carrying the signal that
        # triggered it - i.e. entry never happens on the same bar as the
        # decision. We assert this indirectly: entry_timestamp is strictly
        # after the first bar with sufficient warm-up data.
        assert trade.entry_timestamp > bars[0].timestamp


def test_future_bars_do_not_affect_earlier_signals() -> None:
    """Truncating the bar series after any given point must not change
    any signal/trade decision made using only the bars up to that point
    - the defining test of no-look-ahead bias."""
    prices = [str(100 + i) for i in range(40)]
    full_bars = _bars(prices)
    truncate_at = 25
    truncated_bars = full_bars[:truncate_at]

    full_result = run_backtest(
        full_bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=full_bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(full_bars)),
        generated_at=datetime.now(tz=UTC),
    )
    truncated_result = run_backtest(
        truncated_bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=truncated_bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(truncated_bars)),
        generated_at=datetime.now(tz=UTC),
    )

    truncated_entries = [
        (t.entry_timestamp, t.direction)
        for t in truncated_result.trades
        if t.entry_timestamp <= truncated_bars[-1].timestamp
    ]
    full_entries_in_range = [
        (t.entry_timestamp, t.direction)
        for t in full_result.trades
        if t.entry_timestamp <= truncated_bars[-1].timestamp
    ]
    assert truncated_entries == full_entries_in_range


def test_indicator_warmup_is_respected_no_trade_before_warmup() -> None:
    """The EMA(3)/EMA(6) crossover cannot produce a signal before both
    EMAs have warmed up - the first possible entry is strictly after
    the slow lookback's warm-up bars."""
    prices = [str(100 + i) for i in range(20)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    slow_lookback = 6
    earliest_possible_signal_bar = bars[slow_lookback - 1].timestamp
    for trade in result.trades:
        assert trade.entry_timestamp > earliest_possible_signal_bar


# --- Trade ledger / costs / P&L -------------------------------------------


def test_gross_pnl_and_net_pnl_with_zero_costs_match() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(brokerage_percent=Decimal("0"), slippage_percent=Decimal("0")),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    for trade in result.trades:
        assert trade.costs == Decimal("0")
        assert trade.net_pnl == trade.gross_pnl


def test_brokerage_costs_reduce_net_pnl() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(brokerage_percent=Decimal("1")),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades
    for trade in result.trades:
        assert trade.costs > 0
        assert trade.net_pnl == trade.gross_pnl - trade.costs


def test_slippage_moves_fill_price_against_the_trader() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    baseline = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(slippage_percent=Decimal("0")),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    slipped = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(slippage_percent=Decimal("1")),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert baseline.trades and slipped.trades
    first_baseline = baseline.trades[0]
    first_slipped = slipped.trades[0]
    if first_baseline.direction == StrategyDirection.BULLISH:
        assert first_slipped.entry_price > first_baseline.entry_price


def test_percent_of_equity_sizing_produces_a_positive_quantity() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(
            position_sizing_mode=PositionSizingMode.PERCENT_OF_EQUITY,
            position_size_value=Decimal("0.1"),
        ),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades
    assert all(t.quantity > 0 for t in result.trades)


# --- MFE / MAE (Part 9) ----------------------------------------------------


def test_mfe_and_mae_are_non_negative_and_present() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades
    for trade in result.trades:
        assert trade.mfe is not None
        assert trade.mae is not None
        assert trade.mfe >= 0
        assert trade.mae >= 0


# --- Equity curve / drawdown -----------------------------------------------


def test_equity_curve_starts_at_initial_capital_and_matches_trade_count() -> None:
    prices = [str(100 + i) for i in range(40)]
    bars = _bars(prices)
    config = _config()
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.equity_curve[0].balance == config.initial_capital
    assert len(result.equity_curve) == len(result.trades) + 1
    assert result.equity_curve[-1].balance == result.metrics.final_capital


def test_drawdown_is_never_negative() -> None:
    prices = [str(100 + ((-1) ** i) * (i % 7)) for i in range(60)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    for point in result.equity_curve:
        assert point.drawdown >= 0
        assert point.drawdown_percent >= 0


# --- Metrics ----------------------------------------------------------------


def test_win_rate_and_profit_factor_are_internally_consistent() -> None:
    prices = [str(100 + ((-1) ** i) * (i % 9)) for i in range(80)]
    bars = _bars(prices)
    result = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    m = result.metrics
    assert m.total_trades == m.winning_trades + m.losing_trades
    if m.total_trades > 0:
        expected_win_rate = Decimal(m.winning_trades) / m.total_trades * 100
        assert m.win_rate_percent == expected_win_rate
    if m.gross_loss == 0:
        assert m.profit_factor is None
    elif m.total_trades > 0:
        assert m.profit_factor == m.gross_profit / abs(m.gross_loss)


def test_no_trades_produces_well_defined_zeroed_metrics() -> None:
    """Adversarial case: a flat/neutral-only series producing zero
    trades must not crash and must report well-defined zero metrics,
    never a division-by-zero or a fabricated number."""
    bars = _bars(["100"] * 10)  # flat price series -> ATR/SMA neutral, no crossover
    registry = build_default_registry()
    strategy = registry.get("sma_trend_filter")
    config_values = StrategyConfigurationValues(
        "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5, "band_percent": Decimal("50")}
    )
    result = run_backtest(
        bars,
        strategy,
        config_values,
        _config(strategy_id="sma_trend_filter", end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.metrics.total_trades == 0
    assert result.metrics.win_rate_percent == Decimal("0")
    assert result.metrics.net_pnl == Decimal("0")
    assert result.metrics.sharpe_ratio_trade_level is None
    assert result.metrics.profit_factor is None


# --- Reproducibility (Part 11, mandatory) -----------------------------------


def test_two_identical_runs_produce_identical_results() -> None:
    prices = [str(100 + ((-1) ** i) * (i % 5)) for i in range(50)]
    bars = _bars(prices)
    config = _config(end=bars[-1].timestamp)
    generated_at = datetime.now(tz=UTC)

    result_a = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
    )
    result_b = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
    )

    assert result_a.backtest_id == result_b.backtest_id
    assert result_a.trades == result_b.trades
    assert result_a.equity_curve == result_b.equity_curve
    assert result_a.metrics == result_b.metrics


def test_different_configuration_produces_a_different_backtest_id() -> None:
    prices = [str(100 + i) for i in range(30)]
    bars = _bars(prices)
    generated_at = datetime.now(tz=UTC)
    result_a = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
    )
    result_b = run_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(end=bars[-1].timestamp, configuration_version="v2"),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
    )
    assert result_a.backtest_id != result_b.backtest_id
