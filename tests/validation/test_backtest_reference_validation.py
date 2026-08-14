# tests/validation/test_backtest_reference_validation.py
#
# Checkpoint 30: the core independent-reference validation suite.
# Compares `src/intraday/research/backtesting`'s real engine against
# `tests/validation/reference_engine.py`'s independently-derived
# implementation, on the SAME frozen bar data, SAME strategy rule, SAME
# execution timing, SAME verified cost schedule.
#
# Differential classification (Part 11): every comparison in this file
# asserts EXACT equality (after Decimal normalization) - this checkpoint
# found no case requiring ACCEPTABLE_ROUNDING_DIFFERENCE or
# EXPLAINED_SEMANTIC_DIFFERENCE tolerance; both implementations agree
# exactly. Any assertion failure below is by definition an
# UNEXPLAINED_MISMATCH and a checkpoint failure - no tolerance was
# loosened to make a test pass.
from __future__ import annotations

from datetime import UTC, datetime
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
from intraday.research.backtesting.cost_model import verified_nse_cash_equity_intraday_cost_model
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
from tests.validation.fixtures import (
    extended_fixture,
    micro_fixture,
    second_instrument_for_portfolio,
)
from tests.validation.reference_engine import (
    ReferenceBar,
    run_reference_backtest,
    run_reference_portfolio,
)

FAST_LOOKBACK = 3
SLOW_LOOKBACK = 6
QUANTITY = Decimal("10")
INITIAL_CAPITAL = Decimal("100000")

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


def _to_domain_bars(
    instrument_id: str, reference_bars: tuple[ReferenceBar, ...]
) -> tuple[Bar, ...]:
    """Converts the reference fixture's plain `ReferenceBar` records into
    the production domain `Bar` type - the ONE conversion point between
    the two independent implementations' data representations."""
    return tuple(
        Bar(
            instrument_id=instrument_id,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=datetime.fromisoformat(rb.timestamp),
            open=rb.open,
            high=rb.high,
            low=rb.low,
            close=rb.close,
            volume=Decimal("0"),
        )
        for rb in reference_bars
    )


def _dq(bar_count: int) -> DataQualityDisclosure:
    return DataQualityDisclosure(
        data_source="frozen validation fixture (synthetic)",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=bar_count,
        missing_bar_note="none",
        transaction_cost_assumption="verified Indian schedule",
        slippage_assumption="none (zero-slippage controlled comparison)",
        survivorship_bias_note="n/a - synthetic",
    )


def _run_engine(instrument_id: str, domain_bars: tuple[Bar, ...]):
    config = BacktestConfiguration(
        instrument_id=instrument_id,
        timeframe=Timeframe.ONE_MINUTE,
        start=domain_bars[0].timestamp,
        end=domain_bars[-1].timestamp,
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=INITIAL_CAPITAL,
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=QUANTITY,
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )
    strategy_config = StrategyConfigurationValues(
        "ema_crossover",
        "v1",
        "v1",
        "v1",
        {"fast_lookback": FAST_LOOKBACK, "slow_lookback": SLOW_LOOKBACK},
    )
    return run_backtest(
        domain_bars,
        REGISTRY.get("ema_crossover"),
        strategy_config,
        config,
        _compute,
        data_quality=_dq(len(domain_bars)),
        generated_at=datetime.now(tz=UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )


# --- Part 13: data integrity of the fixture itself --------------------------


def test_fixture_bars_are_not_corrupted() -> None:
    for fixture in (micro_fixture(), extended_fixture()):
        bars = fixture.bars
        timestamps = [b.timestamp for b in bars]
        assert len(timestamps) == len(set(timestamps)), "duplicate timestamps"
        assert timestamps == sorted(timestamps), "out-of-order timestamps"
        for b in bars:
            assert b.low <= b.open <= b.high
            assert b.low <= b.close <= b.high
            assert b.high >= b.low
            assert b.open > 0 and b.close > 0


def test_fixture_checksum_is_deterministic() -> None:
    a = micro_fixture()
    b = micro_fixture()
    assert a.checksum == b.checksum
    assert a.bars == b.bars


# --- Part 6: signal reconciliation ------------------------------------------


def test_signal_reconciliation_micro_fixture() -> None:
    fixture = micro_fixture()
    domain_bars = _to_domain_bars(fixture.instrument_id, fixture.bars)
    result = _run_engine(fixture.instrument_id, domain_bars)
    reference = run_reference_backtest(
        list(fixture.bars), FAST_LOOKBACK, SLOW_LOOKBACK, INITIAL_CAPITAL, QUANTITY
    )

    # Our engine records signals internally but does not expose the raw
    # per-bar series on BacktestResult - reconcile via the recomputed
    # feature series + strategy.evaluate(), the same public API the
    # engine itself uses, applied bar-by-bar exactly as engine.py does.
    strategy = REGISTRY.get("ema_crossover")
    strategy_config = StrategyConfigurationValues(
        "ema_crossover",
        "v1",
        "v1",
        "v1",
        {"fast_lookback": FAST_LOOKBACK, "slow_lookback": SLOW_LOOKBACK},
    )
    required = strategy.required_features(strategy_config)
    feature_lookup = {
        fid: {fv.timestamp: fv for fv in _compute(fid, domain_bars)} for fid in required
    }

    total_bars = len(domain_bars)
    warmup_bars = 0
    matching = 0
    mismatches: list[str] = []
    for i, bar in enumerate(domain_bars):
        feature_values = {
            fid: feature_lookup[fid][bar.timestamp]
            for fid in required
            if bar.timestamp in feature_lookup[fid]
        }
        ref_signal = reference.signals[i]
        if len(feature_values) < len(required):
            warmup_bars += 1
            assert ref_signal.direction == "NONE", f"warm-up mismatch at bar {i}"
            continue
        our_signal = strategy.evaluate(bar, feature_values, strategy_config)
        our_direction = our_signal.direction.value if our_signal else "NONE"
        if our_direction == ref_signal.direction:
            matching += 1
        else:
            mismatches.append(
                f"bar {i} ({bar.timestamp}): ours={our_direction} reference={ref_signal.direction}"
            )

    assert not mismatches, "UNEXPLAINED_MISMATCH in signal reconciliation:\n" + "\n".join(
        mismatches
    )
    assert total_bars == fixture.bar_count
    assert warmup_bars == SLOW_LOOKBACK - 1
    assert matching == total_bars - warmup_bars
    assert result.validation.warmup_bars == warmup_bars


# --- Part 7: trade-level reconciliation -------------------------------------


def test_trade_reconciliation_micro_fixture() -> None:
    fixture = micro_fixture()
    domain_bars = _to_domain_bars(fixture.instrument_id, fixture.bars)
    result = _run_engine(fixture.instrument_id, domain_bars)
    reference = run_reference_backtest(
        list(fixture.bars), FAST_LOOKBACK, SLOW_LOOKBACK, INITIAL_CAPITAL, QUANTITY
    )

    assert len(result.trades) == len(
        reference.trades
    ), f"trade count mismatch: engine={len(result.trades)} reference={len(reference.trades)}"
    for ours, ref in zip(result.trades, reference.trades, strict=True):
        assert ours.direction.value == ref.direction
        assert ours.entry_timestamp.isoformat() == ref.entry_timestamp
        assert ours.entry_price == ref.entry_price
        assert ours.exit_timestamp.isoformat() == ref.exit_timestamp
        assert ours.exit_price == ref.exit_price
        assert ours.quantity == ref.quantity
        assert ours.reason == ref.reason
        assert ours.gross_pnl == ref.gross_pnl


def test_cost_reconciliation_micro_fixture() -> None:
    fixture = micro_fixture()
    domain_bars = _to_domain_bars(fixture.instrument_id, fixture.bars)
    result = _run_engine(fixture.instrument_id, domain_bars)
    reference = run_reference_backtest(
        list(fixture.bars), FAST_LOOKBACK, SLOW_LOOKBACK, INITIAL_CAPITAL, QUANTITY
    )

    for ours, ref in zip(result.trades, reference.trades, strict=True):
        assert ours.cost_breakdown.brokerage == ref.brokerage
        assert ours.cost_breakdown.stt == ref.stt
        assert ours.cost_breakdown.exchange_transaction_charges == ref.exchange_charges
        assert ours.cost_breakdown.sebi_charges == ref.sebi_charges
        assert ours.cost_breakdown.gst == ref.gst
        assert ours.cost_breakdown.stamp_duty == ref.stamp_duty
        assert ours.costs == ref.total_costs
        assert ours.net_pnl == ref.net_pnl


# --- Part 8: equity / drawdown reconciliation -------------------------------


def test_equity_reconciliation_micro_fixture() -> None:
    fixture = micro_fixture()
    domain_bars = _to_domain_bars(fixture.instrument_id, fixture.bars)
    result = _run_engine(fixture.instrument_id, domain_bars)
    reference = run_reference_backtest(
        list(fixture.bars), FAST_LOOKBACK, SLOW_LOOKBACK, INITIAL_CAPITAL, QUANTITY
    )

    assert len(result.mark_to_market_curve) == len(reference.equity_curve)
    for ours, ref in zip(result.mark_to_market_curve, reference.equity_curve, strict=True):
        assert ours.timestamp.isoformat() == ref.timestamp
        assert ours.realized_pnl == ref.realized_pnl
        assert ours.unrealized_pnl == ref.unrealized_pnl
        assert ours.total_equity == ref.total_equity
        assert ours.peak_equity == ref.peak_equity
        assert ours.drawdown == ref.drawdown

    assert result.metrics.max_drawdown == max(
        (p.drawdown for p in reference.equity_curve), default=Decimal(0)
    )


# --- Extended (larger) fixture: same checks, larger dataset -----------------


def test_signal_and_trade_reconciliation_extended_fixture() -> None:
    fixture = extended_fixture()
    domain_bars = _to_domain_bars(fixture.instrument_id, fixture.bars)
    result = _run_engine(fixture.instrument_id, domain_bars)
    reference = run_reference_backtest(
        list(fixture.bars), FAST_LOOKBACK, SLOW_LOOKBACK, INITIAL_CAPITAL, QUANTITY
    )
    assert len(result.trades) == len(reference.trades)
    assert len(result.trades) > 0, "extended fixture must exercise at least one real trade"
    for ours, ref in zip(result.trades, reference.trades, strict=True):
        assert ours.direction.value == ref.direction
        assert ours.entry_price == ref.entry_price
        assert ours.exit_price == ref.exit_price
        assert ours.net_pnl == ref.net_pnl
        assert ours.cost_breakdown.total == ref.total_costs


# --- Part 10: portfolio validation ------------------------------------------


def test_portfolio_reconciliation_two_instruments() -> None:
    fixture_a = micro_fixture()
    fixture_b = second_instrument_for_portfolio()
    bars_a = _to_domain_bars(fixture_a.instrument_id, fixture_a.bars)
    bars_b = _to_domain_bars(fixture_b.instrument_id, fixture_b.bars)

    assignments = (
        InstrumentAssignment(
            fixture_a.instrument_id,
            "ema_crossover",
            "v1",
            "v1",
            "v1",
            {"fast_lookback": FAST_LOOKBACK, "slow_lookback": SLOW_LOOKBACK},
        ),
        InstrumentAssignment(
            fixture_b.instrument_id,
            "ema_crossover",
            "v1",
            "v1",
            "v1",
            {"fast_lookback": FAST_LOOKBACK, "slow_lookback": SLOW_LOOKBACK},
        ),
    )
    config = PortfolioBacktestConfiguration(
        assignments=assignments,
        timeframe=Timeframe.ONE_MINUTE,
        start=bars_a[0].timestamp,
        end=bars_a[-1].timestamp,
        initial_capital=INITIAL_CAPITAL,
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=QUANTITY,
        max_concurrent_positions=2,
    )
    result = run_portfolio_backtest(
        {fixture_a.instrument_id: bars_a, fixture_b.instrument_id: bars_b},
        {
            fixture_a.instrument_id: REGISTRY.get("ema_crossover"),
            fixture_b.instrument_id: REGISTRY.get("ema_crossover"),
        },
        config,
        _compute,
        data_quality=_dq(len(bars_a)),
        generated_at=datetime.now(tz=UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )

    reference = run_reference_portfolio(
        {
            fixture_a.instrument_id: list(fixture_a.bars),
            fixture_b.instrument_id: list(fixture_b.bars),
        },
        FAST_LOOKBACK,
        SLOW_LOOKBACK,
        INITIAL_CAPITAL,
        QUANTITY,
        max_concurrent_positions=2,
    )

    assert len(result.trades) == len(reference.trades)
    assert result.rejected_entries == reference.rejected_entries
    # Aggregate check (sufficient and simpler than per-instrument keying
    # across two independently-ordered trade lists): total net P&L must
    # match exactly.
    our_total_net = sum((t.net_pnl for t in result.trades), Decimal(0))
    ref_total_net = sum((t.net_pnl for t in reference.trades), Decimal(0))
    assert our_total_net == ref_total_net


# --- Part 14: look-ahead / causality validation (re-confirmed here) --------


def test_truncation_does_not_change_earlier_reference_signals() -> None:
    """The independent reference must demonstrate the same causality
    property Checkpoint 27's own engine test already proves for the
    production engine - truncating the bar series must never change an
    earlier decision."""
    fixture = micro_fixture()
    full_signals = compute_reference_signals_wrapper(fixture.bars, FAST_LOOKBACK, SLOW_LOOKBACK)
    for cutoff in (10, 15, 20, 25):
        truncated_signals = compute_reference_signals_wrapper(
            fixture.bars[:cutoff], FAST_LOOKBACK, SLOW_LOOKBACK
        )
        for i in range(len(truncated_signals)):
            assert (
                truncated_signals[i].direction == full_signals[i].direction
            ), f"look-ahead violation in reference engine at bar {i}, cutoff {cutoff}"


def compute_reference_signals_wrapper(bars, fast, slow):
    from tests.validation.reference_engine import compute_reference_signals

    return compute_reference_signals(list(bars), fast, slow)
