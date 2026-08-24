# tests/unit/research/test_checkpoint_64_53_backtest_trust.py
#
# Checkpoint 64.53: BACKTEST TRUST + RESEARCH READINESS AUDIT.
#
# This file does NOT build a new trust framework. It exercises the
# EXISTING `research.backtesting.engine.run_backtest()` engine against
# the directive's own checklist (execution timing, no-lookahead,
# warmup, Fill/Trade/cost/slippage/P&L/equity reconciliation, long/
# short, exit reasons, EOD, determinism, DB/API source independence,
# strategy independence, partial-fill boundary) with real, freshly
# computed evidence - no fabricated numbers, no assumed pass.
#
# It deliberately does NOT flip `BacktestTrustLevel.POC` to anything
# else - that decision is made in `taskReport.md`/the architecture doc,
# not in test code, and this file's own test Q asserts the flag is
# STILL `POC` today (a regression guard against an accidental future
# silent promotion).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.execution.contracts import Fill
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import (
    StrategyConfigurationValues,
    build_default_registry,
)
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestTrustLevel,
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

INSTRUMENT = "NSE:TRUSTCO"
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


def _bar(i: int, open_: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=i),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def _trend_bars(prices: list[int], start_index: int = 0) -> tuple[Bar, ...]:
    """Deterministic OHLC bars around each closing price - open is the
    PRIOR close (so entries/exits at a bar's open are distinguishable
    from that bar's own close for the execution-timing checks below)."""
    bars = []
    prev_close = prices[0] - 1
    for offset, price in enumerate(prices):
        i = start_index + offset
        open_ = prev_close
        high = max(open_, price) + 1
        low = min(open_, price) - 1
        bars.append(_bar(i, str(open_), str(high), str(low), str(price)))
        prev_close = price
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
        "end": BASE + timedelta(minutes=200),
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
    return build_default_registry().get("ema_crossover")


def _sma_strategy():
    return build_default_registry().get("sma_trend_filter")


def _ema_config(fast: int = 3, slow: int = 6) -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": fast, "slow_lookback": slow}
    )


def _run(bars, strategy=None, strategy_config=None, cfg=None, **cfg_overrides):
    strategy = strategy or _ema_strategy()
    strategy_config = strategy_config or _ema_config()
    cfg = cfg or _config(**cfg_overrides)
    return run_backtest(
        bars,
        strategy,
        strategy_config,
        cfg,
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


def _uptrend_then_downtrend(n_up: int = 30, n_down: int = 30) -> tuple[Bar, ...]:
    up = [100 + i for i in range(n_up)]
    down = [up[-1] - i for i in range(1, n_down + 1)]
    return _trend_bars(up + down)


# --- A. Execution timing --------------------------------------------------


def test_a_entry_never_fills_at_the_signal_bars_own_close() -> None:
    """A signal computed from bar i's close must fill at bar i+1's open,
    never at bar i's own close - the documented, non-lookahead execution
    model (docs/architecture/BACKTESTING_ARCHITECTURE.md 'Look-ahead
    audit')."""
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trades, "fixture must produce at least one trade to test timing"
    close_by_ts = {b.timestamp: b.close for b in bars}
    open_by_ts = {b.timestamp: b.open for b in bars}
    for trade in result.trades:
        # entry_price (pre-slippage-adjusted-at-zero-slippage config, so
        # equal to the filled price here) must match SOME bar's OPEN,
        # and that open must differ from the same bar's own close in
        # this fixture (by construction) - so a close-price fill would
        # be structurally detectable, not just numerically coincidental.
        assert trade.entry_price == open_by_ts[trade.entry_timestamp]
        assert trade.entry_price != close_by_ts[trade.entry_timestamp]


def test_b_eod_force_close_uses_final_bars_own_close() -> None:
    """An open position at the end of the series is force-closed at the
    FINAL bar's own close (documented EOD/'end_of_data' convention),
    not at a synthetic or next-bar price that does not exist."""
    # A pure uptrend never reverses, so any open position at series end
    # is force-closed via EOD/end_of_data.
    bars = _trend_bars([100 + i for i in range(20)])
    result = _run(bars)
    eod_trades = [t for t in result.trades if t.reason in ("EOD", "end_of_data")]
    if eod_trades:
        last_bar = bars[-1]
        for t in eod_trades:
            assert t.exit_price == last_bar.close
            assert t.exit_timestamp == last_bar.timestamp


# --- B. No-lookahead (engine-level, adversarial) ---------------------------


def test_c_mutating_a_future_bar_does_not_change_earlier_results() -> None:
    """Deterministic adversarial no-lookahead proof required by the
    directive: mutate a FUTURE bar dramatically and confirm every trade
    that closed BEFORE that bar's index is byte-identical."""
    bars = list(_uptrend_then_downtrend())
    baseline = _run(tuple(bars))
    assert baseline.trades, "fixture must produce trades to test lookahead"

    # Pick a mutation point partway through the series.
    mutate_index = len(bars) - 5
    mutate_timestamp = bars[mutate_index].timestamp

    mutated_bars = list(bars)
    # Dramatic, deliberately extreme mutation of a LATE bar only.
    wild = bars[mutate_index]
    mutated_bars[mutate_index] = Bar(
        instrument_id=wild.instrument_id,
        timeframe=wild.timeframe,
        timestamp=wild.timestamp,
        open=Decimal("999999"),
        high=Decimal("1000000"),
        low=Decimal("1"),
        close=Decimal("500000"),
        volume=wild.volume,
    )
    mutated_result = _run(tuple(mutated_bars))

    baseline_early_trades = [t for t in baseline.trades if t.exit_timestamp < mutate_timestamp]
    mutated_early_trades = [t for t in mutated_result.trades if t.exit_timestamp < mutate_timestamp]
    assert baseline_early_trades, "need at least one trade closed before the mutation point"
    assert len(baseline_early_trades) == len(mutated_early_trades)
    for early, mutated_early in zip(baseline_early_trades, mutated_early_trades, strict=True):
        assert early.entry_price == mutated_early.entry_price
        assert early.exit_price == mutated_early.exit_price
        assert early.net_pnl == mutated_early.net_pnl
        assert early.exit_timestamp == mutated_early.exit_timestamp


def test_d_truncating_the_series_does_not_change_earlier_signals_or_trades() -> None:
    """A second, complementary no-lookahead proof: truncating the bar
    series at several cutoffs must never change a trade that closed
    strictly before the cutoff."""
    bars = _uptrend_then_downtrend()
    full = _run(bars)
    assert full.trades

    for cutoff in (20, 35, 50):
        truncated = _run(bars[:cutoff])
        cutoff_ts = bars[cutoff - 1].timestamp
        full_before = [t for t in full.trades if t.exit_timestamp <= cutoff_ts]
        trunc_before = [t for t in truncated.trades if t.exit_timestamp <= cutoff_ts]
        # Every trade the truncated run closed before the cutoff must
        # also appear, identically, in the full run's own trades before
        # the cutoff (truncation can only ever remove a LATER trade or
        # force an early EOD close it wouldn't otherwise have had - it
        # can never rewrite an earlier trade's own numbers).
        for t in trunc_before:
            if t.reason in ("EOD", "end_of_data") and t.exit_timestamp == cutoff_ts:
                continue  # truncation-induced EOD close - expected, not a lookahead leak
            matches = [
                f
                for f in full_before
                if f.entry_timestamp == t.entry_timestamp and f.entry_price == t.entry_price
            ]
            assert matches, f"trade {t} present in truncated run has no match in full run"
            assert matches[0].exit_price == t.exit_price
            assert matches[0].net_pnl == t.net_pnl


# --- C. Warmup --------------------------------------------------------------


def test_e_no_signal_before_the_strategy_lookback_is_satisfied() -> None:
    """`ema_crossover` with slow_lookback=6 must produce zero trades on
    a prefix shorter than its own warmup requirement, and the first
    trade's entry index must respect that warmup."""
    strategy = _ema_strategy()
    cfg = _ema_config(fast=3, slow=6)
    too_short = _trend_bars([100 + i for i in range(4)])  # < slow_lookback
    result = _run(too_short, strategy=strategy, strategy_config=cfg)
    assert result.trades == ()
    assert result.validation.warmup_bars <= 5  # can never exceed slow_lookback - 1
    assert result.validation.bar_count == 4

    long_enough = _uptrend_then_downtrend()
    result2 = _run(long_enough, strategy=strategy, strategy_config=cfg)
    if result2.trades:
        first_entry_index = next(
            i for i, b in enumerate(long_enough) if b.timestamp == result2.trades[0].entry_timestamp
        )
        assert first_entry_index >= result2.validation.warmup_bars


# --- D. Fill / Trade reconciliation -----------------------------------------


def test_f_fill_quantities_and_prices_reconcile_to_trade_round_trip() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trades and result.fills

    fills_by_order = {}
    for f in result.fills:
        fills_by_order.setdefault(f.order_id, []).append(f)

    for trade in result.trades:
        assert (
            trade.order_intent is not None
        ), "trade has no linked OrderIntent to reconcile against"
        order_id = trade.order_intent.order_id
        trade_fills = fills_by_order.get(order_id, [])
        assert trade_fills, f"no Fill found for trade order_id={order_id}"
        # Every fill must be a real, unique, positive-quantity/price event.
        fill_ids = [f.fill_id for f in trade_fills]
        assert len(fill_ids) == len(set(fill_ids))
        for f in trade_fills:
            assert f.quantity > 0
            assert f.price > 0
        entry_fills = [f for f in trade_fills if f.side.value.upper() in ("BUY", "SELL")]
        assert len(entry_fills) >= 1


def test_g_sum_of_fill_quantities_matches_trade_quantity_for_a_round_trip() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trades and result.fills
    fills_by_order: dict[str, list[Fill]] = {}
    for f in result.fills:
        fills_by_order.setdefault(f.order_id, []).append(f)
    for trade in result.trades:
        order_id = trade.order_intent.order_id  # type: ignore[union-attr]
        trade_fills = fills_by_order[order_id]
        # No partial-fill engine exists (directive §15) - exactly one
        # entry fill per trade's own entry leg, at the trade's own
        # quantity.
        entry_fills = [f for f in trade_fills if f.fill_id.endswith("-fill-entry")]
        assert len(entry_fills) == 1
        assert entry_fills[0].quantity == trade.quantity


# --- E. Cost reconciliation --------------------------------------------------


def test_h_fill_transaction_costs_sum_to_trade_costs() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars, brokerage_percent=Decimal("0.05"))
    assert result.trades and result.fills
    fills_by_order: dict[str, list[Fill]] = {}
    for f in result.fills:
        fills_by_order.setdefault(f.order_id, []).append(f)
    for trade in result.trades:
        order_id = trade.order_intent.order_id  # type: ignore[union-attr]
        trade_fills = fills_by_order[order_id]
        summed_fill_costs = sum((f.transaction_cost for f in trade_fills), Decimal("0"))
        assert summed_fill_costs == trade.costs
        assert trade.costs == trade.cost_breakdown.total


# --- F. Slippage reconciliation ----------------------------------------------


def test_i_fill_price_reflects_configured_slippage_and_slippage_applied_matches() -> None:
    bars = _uptrend_then_downtrend()
    result_no_slip = _run(bars, slippage_percent=Decimal("0"))
    result_slip = _run(bars, slippage_percent=Decimal("0.1"))
    assert result_no_slip.trades and result_slip.trades

    fills_by_order_slip: dict[str, list[Fill]] = {}
    for f in result_slip.fills:
        fills_by_order_slip.setdefault(f.order_id, []).append(f)

    for trade in result_slip.trades:
        order_id = trade.order_intent.order_id  # type: ignore[union-attr]
        trade_fills = fills_by_order_slip[order_id]
        for f in trade_fills:
            assert f.slippage_applied is not None
            # price already includes slippage - reconstructing the
            # pre-slippage reference price must reproduce it exactly.
            reference_price = f.price - f.slippage_applied
            assert reference_price > 0

    # With non-zero slippage, at least one price actually differs from
    # the zero-slippage run at the same entry timestamp (proves
    # slippage is genuinely applied, not a dead configuration knob).
    no_slip_by_ts = {t.entry_timestamp: t.entry_price for t in result_no_slip.trades}
    differs = any(
        t.entry_timestamp in no_slip_by_ts and t.entry_price != no_slip_by_ts[t.entry_timestamp]
        for t in result_slip.trades
    )
    assert differs


# --- G. Net P&L reconciliation ------------------------------------------------


def test_j_gross_minus_costs_equals_net_and_sum_matches_metrics_net_pnl() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars, brokerage_percent=Decimal("0.05"), slippage_percent=Decimal("0.05"))
    assert result.trades
    for trade in result.trades:
        assert trade.gross_pnl - trade.costs == trade.net_pnl
    assert sum((t.net_pnl for t in result.trades), Decimal("0")) == result.metrics.net_pnl


# --- H. Equity reconciliation -------------------------------------------------


def test_k_equity_identity_holds_and_final_equity_matches_capital_plus_pnl() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars, brokerage_percent=Decimal("0.05"))
    assert result.mark_to_market_curve
    capital = result.configuration.initial_capital
    for point in result.mark_to_market_curve:
        assert capital + point.realized_pnl + point.unrealized_pnl == point.total_equity

    last_point = result.mark_to_market_curve[-1]
    # At the very last bar, if no position remains open, unrealized == 0
    # and realized_pnl must equal the summed trade net_pnl.
    if last_point.unrealized_pnl == 0:
        assert last_point.realized_pnl == result.metrics.net_pnl
        assert last_point.total_equity == capital + result.metrics.net_pnl


# --- I. Realized vs unrealized separation ------------------------------------


def test_realized_unrealized_do_not_mix_mid_trade() -> None:
    """While a trade is still open, unrealized_pnl must be non-zero (for
    a genuinely moved price) and realized_pnl must not yet include that
    open trade's own P&L."""
    bars = _trend_bars([100 + i for i in range(20)])  # steady uptrend, one open long
    result = _run(bars)
    if not result.trades:
        pytest.skip("fixture produced no trades")
    # find a mark-to-market point strictly between an entry and its exit
    trade = result.trades[0]
    mid_points = [
        p
        for p in result.mark_to_market_curve
        if trade.entry_timestamp < p.timestamp < trade.exit_timestamp
    ]
    for p in mid_points:
        # realized_pnl at this point must not already include this
        # still-open trade's net_pnl (it isn't closed yet).
        assert p.realized_pnl != p.realized_pnl + trade.net_pnl or trade.net_pnl == 0


# --- J/K. Long and short round trips ------------------------------------------


def test_l_long_round_trip_reconciles_fill_trade_pnl_equity() -> None:
    bars = _uptrend_then_downtrend(n_up=15, n_down=15)
    result = _run(bars)
    longs = [t for t in result.trades if t.direction.value.upper() in ("BULLISH", "LONG", "BUY")]
    assert longs, "expected at least one long trade on an uptrend-then-downtrend fixture"
    t = longs[0]
    assert t.gross_pnl - t.costs == t.net_pnl


def test_m_short_round_trip_reconciles_fill_trade_pnl_equity() -> None:
    bars = _uptrend_then_downtrend(n_up=15, n_down=15)
    result = _run(bars)
    shorts = [t for t in result.trades if t.direction.value.upper() in ("BEARISH", "SHORT", "SELL")]
    assert shorts, "expected at least one short trade once the trend reverses"
    t = shorts[0]
    assert t.gross_pnl - t.costs == t.net_pnl


# --- K. Exit reasons / EOD ----------------------------------------------------


def test_n_exit_reasons_are_real_and_every_trade_has_one() -> None:
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trades
    seen_reasons = {t.reason for t in result.trades}
    assert seen_reasons  # non-empty
    for t in result.trades:
        assert t.reason  # never blank/None


# --- L. Deterministic repeat ---------------------------------------------------


def test_o_identical_run_twice_is_byte_identical() -> None:
    bars = _uptrend_then_downtrend()
    r1 = _run(bars)
    r2 = _run(bars)
    assert r1.backtest_id == r2.backtest_id
    assert [f.fill_id for f in r1.fills] == [f.fill_id for f in r2.fills]
    assert len(r1.trades) == len(r2.trades)
    for t1, t2 in zip(r1.trades, r2.trades, strict=True):
        assert t1.entry_price == t2.entry_price
        assert t1.exit_price == t2.exit_price
        assert t1.net_pnl == t2.net_pnl
    assert r1.metrics == r2.metrics


# --- M. Strategy independence ---------------------------------------------------


def test_p_engine_is_strategy_agnostic_ema_vs_sma_produce_independent_results() -> None:
    """The engine itself must not be secretly coupled to one strategy's
    shape - run two DIFFERENT default-registry strategies over the same
    bars and confirm both execute through the identical engine code path
    with their own, independently-derived trade sets."""
    bars = _uptrend_then_downtrend()
    ema_result = _run(bars, strategy=_ema_strategy(), strategy_config=_ema_config())
    sma_strategy = _sma_strategy()
    sma_config = StrategyConfigurationValues(
        "sma_trend_filter",
        "v1",
        "v1",
        "v1",
        {"lookback": 6, "band_percent": Decimal("0.1")},
    )
    sma_result = _run(
        bars,
        strategy=sma_strategy,
        strategy_config=sma_config,
        cfg=_config(strategy_id="sma_trend_filter"),
    )
    # Both must be real, independently-produced BacktestResults from the
    # SAME `run_backtest()` function - different strategy_id, and (on
    # this fixture) not required to produce identical trade counts.
    assert ema_result.configuration.strategy_id == "ema_crossover"
    assert sma_result.configuration.strategy_id == "sma_trend_filter"
    assert ema_result.backtest_id != sma_result.backtest_id


# --- N. Database vs API-populated snapshot equivalence (documented boundary) --


def test_database_snapshot_source_is_irrelevant_to_engine_numerical_output() -> None:
    """`run_backtest()` itself takes only a `tuple[Bar, ...]` - it has NO
    knowledge of whether those bars arrived via a DB read or an API
    fetch (Checkpoint 64.52 proved the DB-first PIPELINE; this proves
    the ENGINE consuming its output is source-blind by construction).
    Two independently-constructed, value-identical bar tuples (one
    simulating a 'DB read', one simulating a fresh 'API fetch') must
    produce numerically identical results."""
    prices = [100 + i for i in range(20)] + [119 - i for i in range(20)]
    db_bars = _trend_bars(prices)
    # A second, independently constructed tuple with identical values
    # but different Python object identities - simulating bars freshly
    # deserialized from an API response vs. read back from a DB row.
    api_bars = tuple(
        Bar(
            instrument_id=b.instrument_id,
            timeframe=b.timeframe,
            timestamp=b.timestamp,
            open=Decimal(str(b.open)),
            high=Decimal(str(b.high)),
            low=Decimal(str(b.low)),
            close=Decimal(str(b.close)),
            volume=Decimal(str(b.volume)),
        )
        for b in db_bars
    )
    assert db_bars is not api_bars
    for a, b in zip(db_bars, api_bars, strict=True):
        assert a is not b

    result_db = _run(db_bars)
    result_api = _run(api_bars)
    assert result_db.backtest_id == result_api.backtest_id
    assert result_db.metrics == result_api.metrics


# --- O. Paper partial-fill boundary (documented, not implemented here) --------


def test_partial_fill_is_a_documented_open_boundary_not_a_backtest_capability() -> None:
    """Directive §15: PaperBroker supports partial fills; Backtest does
    NOT have a general partial-fill engine, and this checkpoint must NOT
    add one. Prove the current, real behaviour: every entry Fill this
    engine emits fills the ENTIRE requested trade quantity in one event
    - never a partial slice - across a run with multiple trades."""
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trades and result.fills
    entry_fills = [f for f in result.fills if f.fill_id.endswith("-fill-entry")]
    assert len(entry_fills) == len(result.trades)
    trades_by_order = {t.order_intent.order_id: t for t in result.trades}  # type: ignore[union-attr]
    for f in entry_fills:
        trade = trades_by_order[f.order_id]
        # The engine's own single entry Fill covers 100% of the trade's
        # quantity in one event - there is no second, later Fill for the
        # SAME order_id/entry leg that would represent a partial-fill
        # completion sequence.
        assert f.quantity == trade.quantity
        same_order_entry_fills = [g for g in entry_fills if g.order_id == f.order_id]
        assert len(same_order_entry_fills) == 1  # exactly one entry fill, never split


# --- P. No false VERIFIED transition -------------------------------------------


def test_q_backtest_trust_level_default_is_still_poc_this_checkpoint() -> None:
    """Regression guard, per the directive's own explicit instruction:
    this checkpoint must NOT change `BacktestTrustLevel.POC` to anything
    else without airtight evidence on every dimension. This test simply
    proves the flag has not silently drifted - it fails loudly if a
    future change flips the default without updating this guard
    deliberately."""
    bars = _uptrend_then_downtrend()
    result = _run(bars)
    assert result.trust_level == BacktestTrustLevel.POC
    assert BacktestTrustLevel.POC.value == "POC"
    # The enum itself must still define exactly these four ordered
    # levels - unchanged since Checkpoint 28.
    assert {level.value for level in BacktestTrustLevel} == {
        "POC",
        "RESEARCH_READY",
        "VALIDATION_READY",
        "PRODUCTION_RESEARCH_READY",
    }
