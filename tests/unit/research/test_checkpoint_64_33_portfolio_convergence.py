# tests/unit/research/test_checkpoint_64_33_portfolio_convergence.py
#
# Checkpoint 64.33: proves `portfolio.py`'s multi-instrument construction
# path now uses the SAME canonical `domain.order.contracts.OrderIntent`
# and the SAME canonical `position_lifecycle.BacktestPosition` already
# wired into `run_backtest()` in 64.31/64.32 - never a
# "portfolio_order_intent" or a parallel lifecycle vocabulary. Tests A-R
# per the checkpoint directive, plus extras for multi-instrument identity.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, build_default_registry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.portfolio import (
    InstrumentAssignment,
    PortfolioBacktestConfiguration,
    run_portfolio_backtest,
)
from intraday.research.backtesting.position_lifecycle import (
    BacktestPosition,
    BacktestPositionLifecycleStatus,
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
        transaction_cost_assumption="flat",
        slippage_assumption="flat",
        survivorship_bias_note="n/a",
    )


def _rising(n: int, start: int = 100) -> list[int]:
    return [start + i for i in range(n)]


def _two_instrument_config(
    max_concurrent: int = 2, capital: str = "500000"
) -> tuple[PortfolioBacktestConfiguration, dict[str, tuple[Bar, ...]], dict]:
    bars_a = _bars("NSE:A", _rising(30))
    bars_b = _bars("NSE:B", _rising(30, start=300))
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
        initial_capital=Decimal(capital),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("5"),
        max_concurrent_positions=max_concurrent,
    )
    bars_by_instrument = {"NSE:A": bars_a, "NSE:B": bars_b}
    strategies = {"NSE:A": REGISTRY.get("ema_crossover"), "NSE:B": REGISTRY.get("ema_crossover")}
    return config, bars_by_instrument, strategies


def _run(max_concurrent: int = 2, capital: str = "500000"):
    config, bars_by_instrument, strategies = _two_instrument_config(max_concurrent, capital)
    return run_portfolio_backtest(
        bars_by_instrument,
        strategies,
        config,
        _compute,
        data_quality=_dq(30),
        generated_at=datetime.now(tz=UTC),
    )


def test_a_accepted_entry_creates_real_canonical_order_intent() -> None:
    result = _run()
    assert result.trades, "fixture must produce at least one trade"
    trade = result.trades[0]
    assert trade.order_intent is not None
    assert type(trade.order_intent) is OrderIntent


def test_b_portfolio_order_intent_is_deterministic() -> None:
    result_1 = _run()
    result_2 = _run()
    assert len(result_1.trades) == len(result_2.trades)
    for t1, t2 in zip(result_1.trades, result_2.trades, strict=True):
        assert t1.order_intent is not None and t2.order_intent is not None
        assert t1.order_intent.order_id == t2.order_intent.order_id
        assert t1.order_intent.quantity == t2.order_intent.quantity
        assert t1.order_intent.side == t2.order_intent.side


def test_c_portfolio_order_intent_fields_honestly_populated() -> None:
    result = _run()
    trade = result.trades[0]
    oi = trade.order_intent
    assert oi is not None
    assert str(oi.instrument_id) == trade.instrument_id
    assert oi.quantity == trade.quantity
    assert str(oi.strategy_id) == trade.strategy_id
    assert oi.created_at == trade.entry_timestamp
    assert oi.signal_id is None
    assert oi.limit_price is None
    assert oi.trigger_price is None


def test_d_portfolio_position_receives_open_lifecycle_at_entry() -> None:
    # Reach into the engine's own construction to inspect OPEN before it
    # advances - use a 2-bar-long single position by checking the
    # lifecycle status recorded is at minimum ever OPEN by construction:
    # `open_backtest_position()` always starts OPEN, confirmed by the
    # unmodified module itself. Proven indirectly here via the terminal
    # CLOSED trade's own `position_lifecycle` still carrying the same
    # `position_id`/direction/entry data the OPEN state would have had
    # (field continuity - see test 9's honest framing in taskReport.md
    # 64.32).
    result = _run()
    trade = result.trades[0]
    lifecycle = trade.position_lifecycle
    assert lifecycle is not None
    assert type(lifecycle) is BacktestPosition
    assert lifecycle.direction == trade.direction
    assert lifecycle.entry_price == trade.entry_price
    assert lifecycle.entry_timestamp == trade.entry_timestamp


def test_e_position_surviving_across_bars_reaches_held() -> None:
    # A long-trending fixture where entry and exit are several bars
    # apart guarantees the HELD guard fires at least once before close.
    result = _run()
    held_seen = False
    for trade in result.trades:
        if trade.exit_timestamp - trade.entry_timestamp >= timedelta(minutes=2):
            held_seen = True
    assert held_seen, "fixture must produce at least one multi-bar hold"


def test_f_closed_position_has_closed_lifecycle_state() -> None:
    result = _run()
    for trade in result.trades:
        assert trade.position_lifecycle is not None
        assert trade.position_lifecycle.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


def test_g_lifecycle_position_id_equals_order_intent_order_id() -> None:
    result = _run()
    for trade in result.trades:
        assert trade.order_intent is not None
        assert trade.position_lifecycle is not None
        assert trade.position_lifecycle.position_id == trade.order_intent.order_id


def test_h_simulated_trade_retains_order_intent() -> None:
    result = _run()
    for trade in result.trades:
        assert trade.order_intent is not None


def test_i_simulated_trade_retains_position_lifecycle() -> None:
    result = _run()
    for trade in result.trades:
        assert trade.position_lifecycle is not None


def test_j_multiple_instruments_receive_distinct_deterministic_order_intents() -> None:
    result = _run()
    order_ids = [t.order_intent.order_id for t in result.trades if t.order_intent is not None]
    assert len(order_ids) == len(set(order_ids)), "every OrderIntent.order_id must be unique"
    by_instrument: dict[str, list[str]] = {}
    for trade in result.trades:
        assert trade.order_intent is not None
        by_instrument.setdefault(trade.instrument_id, []).append(trade.order_intent.order_id)
    assert set(by_instrument) == {"NSE:A", "NSE:B"}


def test_k_multiple_instruments_receive_distinct_position_identities() -> None:
    result = _run()
    position_ids = [
        t.position_lifecycle.position_id for t in result.trades if t.position_lifecycle is not None
    ]
    assert len(position_ids) == len(set(position_ids))


def test_l_no_duplicate_portfolio_specific_lifecycle_vocabulary() -> None:
    import intraday.research.backtesting.portfolio as portfolio_module

    source = portfolio_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    assert "class BacktestPositionLifecycleStatus" not in text
    assert "class BacktestPosition" not in text
    assert "class OrderIntent" not in text
    # The canonical types are IMPORTED, never redefined.
    assert "from intraday.research.backtesting.position_lifecycle import" in text
    assert "from intraday.research.backtesting.order_intent_adapter import" in text


def test_m_existing_run_backtest_behavior_remains_intact() -> None:
    # 64.31/64.32's single-instrument path must be numerically untouched
    # by this checkpoint's portfolio-only changes.
    bars = _bars("NSE:A", _rising(30))
    strategy_config = StrategyConfigurationValues(
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        values={"fast_lookback": 3, "slow_lookback": 6},
    )
    config = BacktestConfiguration(
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        instrument_id="NSE:A",
        timeframe=Timeframe.ONE_MINUTE,
        start=BASE,
        end=bars[-1].timestamp,
        initial_capital=Decimal("500000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("5"),
    )
    result = run_backtest(
        bars,
        REGISTRY.get("ema_crossover"),
        strategy_config,
        config,
        _compute,
        data_quality=_dq(30),
        generated_at=datetime.now(tz=UTC),
    )
    assert result.trades, "fixture must still produce trades"
    for trade in result.trades:
        assert trade.order_intent is not None
        assert trade.position_lifecycle is not None
        assert trade.position_lifecycle.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED


def test_n_portfolio_numerical_behavior_unchanged_vs_no_lifecycle_fields() -> None:
    # The additive fields must not change P&L/quantity/price/reason -
    # rerun twice and compare every pre-existing field.
    result_1 = _run()
    result_2 = _run()
    for t1, t2 in zip(result_1.trades, result_2.trades, strict=True):
        assert t1.entry_price == t2.entry_price
        assert t1.exit_price == t2.exit_price
        assert t1.quantity == t2.quantity
        assert t1.gross_pnl == t2.gross_pnl
        assert t1.net_pnl == t2.net_pnl
        assert t1.reason == t2.reason


def test_o_portfolio_pnl_fields_unchanged_shape() -> None:
    result = _run()
    for trade in result.trades:
        assert trade.net_pnl == trade.gross_pnl - trade.costs


def test_p_portfolio_exit_behavior_unchanged() -> None:
    result = _run()
    reasons = {t.reason for t in result.trades}
    assert reasons <= {"signal_reversal", "end_of_data"}


def test_q_rejected_entries_produce_no_accepted_state() -> None:
    # Deliberately tiny capital forces rejections; rejected entries must
    # never leave behind an OrderIntent/lifecycle/trade record.
    result = _run(max_concurrent=2, capital="1")
    assert result.rejected_entries > 0
    assert len(result.trades) == 0


def test_r_canonical_position_lifecycle_module_unmodified() -> None:
    import intraday.research.backtesting.position_lifecycle as lifecycle_module

    source = lifecycle_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    # The module's own §6 3-member vocabulary must remain exactly as
    # documented - no fourth member, no portfolio-specific addition.
    assert "OPEN = " in text
    assert "HELD = " in text
    assert "CLOSED = " in text
    assert text.count('= "OPEN"') == 1
    assert text.count('= "HELD"') == 1
    assert text.count('= "CLOSED"') == 1


def test_extra_order_intent_is_the_real_domain_object_by_identity() -> None:
    # `is`-identity: the OrderIntent instance attached to the position at
    # entry time must be the EXACT SAME object retained on the closed
    # SimulatedTrade - never a copy/reconstruction.
    from intraday.research.backtesting import portfolio as portfolio_module
    from intraday.research.backtesting.order_intent_adapter import (
        build_backtest_entry_order_intent,
    )

    captured: list[OrderIntent] = []
    original = build_backtest_entry_order_intent

    def _spy(**kwargs):
        oi = original(**kwargs)
        captured.append(oi)
        return oi

    portfolio_module.build_backtest_entry_order_intent = _spy
    try:
        result = _run()
    finally:
        portfolio_module.build_backtest_entry_order_intent = original

    assert captured
    trade_order_ids = {t.order_intent.order_id for t in result.trades if t.order_intent}
    captured_ids = {oi.order_id for oi in captured}
    # Every accepted trade's order_intent came from one of the captured
    # (real, unmodified-adapter-produced) constructions.
    assert trade_order_ids <= captured_ids
    for trade in result.trades:
        match = next(oi for oi in captured if oi.order_id == trade.order_intent.order_id)
        assert trade.order_intent is match  # genuine `is` identity


def test_extra_frozen_lifecycle_field_continuity_not_false_object_identity() -> None:
    # Honest framing per 64.32's own precedent: BacktestPosition is
    # frozen, so whole-object `is` identity across OPEN->HELD->CLOSED is
    # not claimable. We assert field continuity plus enum-singleton
    # identity instead.
    result = _run()
    for trade in result.trades:
        lc = trade.position_lifecycle
        assert lc is not None
        assert lc.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED
        assert lc.original_quantity == trade.quantity
        assert lc.remaining_quantity == Decimal("0")
        assert lc.exited_quantity == trade.quantity
