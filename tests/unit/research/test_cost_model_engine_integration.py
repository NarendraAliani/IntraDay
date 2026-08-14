# tests/unit/research/test_cost_model_engine_integration.py
#
# Checkpoint 29: proves the verified Indian cost model plugs into both
# the single-instrument engine and the portfolio engine WITHOUT any
# engine code change (Part 15), that switching cost models changes the
# deterministic backtest identity (Part 9/19), and that
# FlatPercentageCostModel behavior is unchanged (Part 12 regression).
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
from intraday.research.backtesting.cost_model import (
    FlatPercentageCostModel,
    verified_nse_cash_equity_intraday_cost_model,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.portfolio import (
    InstrumentAssignment,
    PortfolioBacktestConfiguration,
    run_portfolio_backtest,
)
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
REGISTRY = build_default_registry()


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


def _bars(instrument: str, prices: list[int]) -> tuple[Bar, ...]:
    bars = []
    for i, p in enumerate(prices):
        price = Decimal(p)
        bars.append(
            Bar(
                instrument_id=instrument,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price - 1,
                high=price + 2,
                low=price - 2,
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
        transaction_cost_assumption="see cost_model_identity",
        slippage_assumption="see cost_model_identity",
        survivorship_bias_note="n/a",
    )


def _config(bars: tuple[Bar, ...]) -> BacktestConfiguration:
    return BacktestConfiguration(
        instrument_id="NSE:TESTCO",
        timeframe=Timeframe.ONE_MINUTE,
        start=bars[0].timestamp,
        end=bars[-1].timestamp,
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0.03"),
        slippage_percent=Decimal("0"),
    )


def _strategy_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


def test_verified_indian_model_plugs_into_single_instrument_engine_unchanged() -> None:
    bars = _bars("NSE:TESTCO", [100 + i for i in range(30)])
    result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        _config(bars),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )
    assert result.cost_model_identity.name == "INDIAN_CASH_EQUITY_INTRADAY"
    assert result.cost_model_identity.is_verified is True
    assert result.trades
    for trade in result.trades:
        assert trade.cost_breakdown.total == trade.costs
        assert trade.net_pnl == trade.gross_pnl - trade.costs


def test_default_flat_percentage_model_is_labeled_not_verified() -> None:
    bars = _bars("NSE:TESTCO", [100 + i for i in range(30)])
    result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        _config(bars),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.cost_model_identity.name == "FLAT_PERCENTAGE"
    assert result.cost_model_identity.is_verified is False


def test_flat_percentage_model_numeric_behavior_is_unchanged_from_checkpoint_28() -> None:
    """Part 12 regression: costs computed with FlatPercentageCostModel
    must exactly equal notional * brokerage_percent / 100 on each leg -
    the same formula Checkpoint 27/28 always used."""
    bars = _bars("NSE:TESTCO", [100 + i for i in range(30)])
    config = _config(bars)
    result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )
    for trade in result.trades:
        entry_notional = trade.entry_price * trade.quantity
        exit_notional = trade.exit_price * trade.quantity
        expected_costs = (entry_notional + exit_notional) * (
            config.brokerage_percent / Decimal("100")
        )
        assert trade.costs == expected_costs
        assert trade.cost_breakdown.stt == 0
        assert trade.cost_breakdown.stamp_duty == 0
        assert trade.cost_breakdown.gst == 0


def test_switching_cost_model_changes_the_backtest_id() -> None:
    bars = _bars("NSE:TESTCO", [100 + i for i in range(30)])
    config = _config(bars)
    generated_at = datetime.now(tz=UTC)
    flat_result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
        cost_model=FlatPercentageCostModel(Decimal("0.03"), Decimal("0")),
    )
    indian_result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )
    assert flat_result.backtest_id != indian_result.backtest_id


def test_same_cost_model_produces_identical_backtest_id_reproducibly() -> None:
    bars = _bars("NSE:TESTCO", [100 + i for i in range(30)])
    config = _config(bars)
    generated_at = datetime.now(tz=UTC)
    r1 = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )
    r2 = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        _strategy_config(),
        config,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )
    assert r1.backtest_id == r2.backtest_id
    assert r1.trades == r2.trades


def test_verified_indian_model_plugs_into_portfolio_engine_unchanged() -> None:
    bars_a = _bars("NSE:A", [100 + i for i in range(25)])
    bars_b = _bars("NSE:B", [200 + i for i in range(25)])
    assignments = (
        InstrumentAssignment(
            "NSE:A", "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
        InstrumentAssignment(
            "NSE:B", "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
    )
    config = PortfolioBacktestConfiguration(
        assignments=assignments,
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=bars_a[-1].timestamp,
        initial_capital=Decimal("200000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        max_concurrent_positions=2,
    )
    result = run_portfolio_backtest(
        {"NSE:A": bars_a, "NSE:B": bars_b},
        {"NSE:A": REGISTRY.get("ema_crossover"), "NSE:B": REGISTRY.get("ema_crossover")},
        config,
        _compute,
        data_quality=_dq(25),
        generated_at=datetime.now(tz=UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )
    assert result.cost_model_identity.name == "INDIAN_CASH_EQUITY_INTRADAY"
    assert result.trades

    # Part 15: portfolio net P&L = sum(trade gross P&L) - sum(auditable costs)
    total_gross = sum((t.gross_pnl for t in result.trades), Decimal("0"))
    total_costs = sum((t.costs for t in result.trades), Decimal("0"))
    total_net = sum((t.net_pnl for t in result.trades), Decimal("0"))
    assert total_net == total_gross - total_costs
    for trade in result.trades:
        assert trade.cost_breakdown.total == trade.costs
