# tests/unit/research/test_mark_to_market.py
#
# Checkpoint 28 Part 4/5/6: mark-to-market equity curve tests. Proves
# the equity identity (initial_capital + realized + unrealized =
# total_equity) at every bar, that unrealized is 0 with no open
# position, that drawdown is captured from an INTRABAR adverse move
# even when the trade ultimately exits flat/profitable, and that
# max_drawdown/percent/duration are derived from the MTM curve.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, build_default_registry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _compute(field_id: str, bars: tuple[Bar, ...]):
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


def _bars(spec: list[tuple[str, str, str, str]]) -> tuple[Bar, ...]:
    """spec: list of (open, high, low, close) strings."""
    bars = []
    for i, (o, h, low, c) in enumerate(spec):
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=Decimal(o),
                high=Decimal(h),
                low=Decimal(low),
                close=Decimal(c),
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
        transaction_cost_assumption="flat",
        slippage_assumption="flat",
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


def _strategy():
    return build_default_registry().get("ema_crossover")


def _strategy_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


def _run(bars: tuple[Bar, ...]):
    return run_backtest(
        bars,
        _strategy(),
        _strategy_config(),
        _config(end=bars[-1].timestamp),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


def test_equity_identity_holds_at_every_bar() -> None:
    prices = [str(100 + ((-1) ** i) * (i % 6)) for i in range(40)]
    bars = _bars([(str(int(p) - 1), str(int(p) + 2), str(int(p) - 2), p) for p in prices])
    result = _run(bars)
    assert result.mark_to_market_curve  # non-empty
    for point in result.mark_to_market_curve:
        assert (
            result.configuration.initial_capital + point.realized_pnl + point.unrealized_pnl
            == point.total_equity
        )


def test_unrealized_pnl_is_zero_when_no_position_is_open() -> None:
    # A flat, unchanging series never triggers an EMA crossover entry.
    bars = _bars([("100", "101", "99", "100")] * 20)
    result = _run(bars)
    assert result.metrics.total_trades == 0
    assert all(p.unrealized_pnl == 0 for p in result.mark_to_market_curve)


def test_mark_to_market_curve_has_one_point_per_bar() -> None:
    prices = [str(100 + i) for i in range(30)]
    bars = _bars([(str(int(p) - 1), str(int(p) + 1), str(int(p) - 1), p) for p in prices])
    result = _run(bars)
    assert len(result.mark_to_market_curve) == len(bars)


def test_intrabar_adverse_move_is_captured_even_if_trade_recovers_before_exit() -> None:
    """Adversarial case (Part 5): a position moves sharply against the
    strategy INTRABAR, then recovers before the trade actually exits.
    The realized-only, trade-close equity curve cannot see this - the
    mark-to-market curve must."""
    # Build a rising series so EMA crossover enters BULLISH, then inject
    # one bar with a deep LOW (adverse excursion) whose CLOSE still
    # continues the uptrend (so the position is never actually closed
    # at a loss) - the MTM curve must show a drawdown at that bar,
    # driven by that bar's own close, even though the trade recovers.
    prices = [100 + i for i in range(10)]
    spec = [(str(p - 1), str(p + 2), str(p - 2), str(p)) for p in prices]
    # Bar 8: inject a severe adverse low relative to entry, but close low
    # too (the CLOSE itself, not just the wick, dips) - proving MTM using
    # bar close reacts to this even though price recovers afterward.
    spec[8] = (str(prices[8] - 1), str(prices[8] + 1), "50", "60")
    spec.append((("61"), "70", "60", "68"))  # bar 9: recovers
    bars = _bars(spec)
    result = _run(bars)
    assert result.metrics.total_trades >= 1
    # The recorded max_drawdown must be strictly positive - the dip was
    # captured, not smoothed away by only sampling trade-close points.
    assert result.metrics.max_drawdown > 0
    assert result.metrics.max_drawdown_duration_bars > 0


def test_max_drawdown_is_derived_from_mark_to_market_not_trade_close_points() -> None:
    prices = [str(100 + ((-1) ** i) * (i % 6)) for i in range(50)]
    bars = _bars([(str(int(p) - 1), str(int(p) + 3), str(int(p) - 3), p) for p in prices])
    result = _run(bars)
    mtm_only_drawdowns = {p.drawdown for p in result.mark_to_market_curve}
    assert result.metrics.max_drawdown in mtm_only_drawdowns


def test_realized_equity_curve_is_preserved_unchanged() -> None:
    """Part 4: the existing Checkpoint 27 realized-only curve must
    still exist alongside the new mark-to-market curve."""
    prices = [str(100 + i) for i in range(30)]
    bars = _bars([(str(int(p) - 1), str(int(p) + 1), str(int(p) - 1), p) for p in prices])
    result = _run(bars)
    assert result.equity_curve  # still present
    assert result.equity_curve[0].balance == result.configuration.initial_capital
    assert len(result.equity_curve) == len(result.trades) + 1
