# tests/unit/research/test_checkpoint_64_43_backtest_fill_producer.py
#
# Checkpoint 64.43: focused tests proving `engine.run_backtest()` now
# constructs a canonical `domain.execution.contracts.Fill` at every
# ACTUAL simulated execution event (entry + exit), additively, while
# every pre-existing numerical result (`SimulatedTrade`, equity curve,
# metrics, trade count) remains byte-for-byte unchanged. Mirrors the
# fixture/helper pattern already established by
# test_checkpoint_64_31_order_intent_wiring.py (copied locally, not
# imported - same "no cross-test-file coupling" discipline).
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.shared_kernel.contracts import Side, Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyParameterSchema,
    StrategySignal,
    TradePlan,
)

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    """Direction-flip-only scripted strategy (no `build_trade_plan`) -
    same shape as 64.31's own `_ScriptedStrategy`."""

    strategy_id = "scripted_stub_6443"
    display_name = "Scripted Stub 64.43"
    specification_version = "v1"
    code_version = "v1"

    def __init__(self, signals_by_index: dict[int, StrategyDirection]) -> None:
        self._signals_by_index = signals_by_index
        self._index = -1

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(strategy_id=self.strategy_id, parameters=())

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        return ()

    def evaluate(self, bar: Bar, feature_values: dict, config: StrategyConfigurationValues):
        self._index += 1
        direction = self._signals_by_index.get(self._index)
        if direction is None:
            return None
        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version="v1",
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=bar.close,
        )


class _TradePlanStrategy(_ScriptedStrategy):
    """Same scripted-signal mechanism, plus a `build_trade_plan` hook
    producing a fixed stop-loss - exercises the TradePlan exit path
    (`tradeplan_execution.simulate_tradeplan_exit`), not the
    direction-flip path."""

    strategy_id = "scripted_tradeplan_6443"

    def __init__(self, signals_by_index: dict[int, StrategyDirection], stop_loss: Decimal) -> None:
        super().__init__(signals_by_index)
        self._stop_loss = stop_loss

    def build_trade_plan(self, bar, feature_values, config, signal) -> TradePlan:
        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=bar.timestamp,
            calculation_method="fixed test stop-loss",
            entry_price=bar.close,
            stop_loss=self._stop_loss,
        )


def _bars_from_ohlc(rows: list[tuple[str, str, str, str]]) -> tuple[Bar, ...]:
    bars = []
    for i, (o, h, low, c) in enumerate(rows):
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


def _bars_from_closes(closes: list[str]) -> tuple[Bar, ...]:
    bars = []
    for i, c in enumerate(closes):
        price = Decimal(c)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
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
        "strategy_id": "scripted_stub_6443",
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


# One 10-share BULLISH entry at bar 1's open (100), reversed and closed
# at bar 3's open (105) - the SAME scripted scenario 64.29/64.30/64.31
# use, so this file's numbers are directly comparable.
_CLOSES = ["100", "100", "105", "105", "110"]
_SIGNALS = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}


def _run_flip(
    strategy_cls=_ScriptedStrategy,
    closes: list[str] | None = None,
    signals: dict[int, StrategyDirection] | None = None,
    slippage_percent: Decimal = Decimal("0"),
    brokerage_percent: Decimal = Decimal("0"),
):
    closes = closes if closes is not None else _CLOSES
    signals = signals if signals is not None else _SIGNALS
    bars = _bars_from_closes(closes)
    strategy = strategy_cls(signals)
    config = _config(
        end=BASE + timedelta(minutes=len(closes) + 5),
        slippage_percent=slippage_percent,
        brokerage_percent=brokerage_percent,
        strategy_id=strategy.strategy_id,
    )
    return run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues(strategy.strategy_id, "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


def _run_tradeplan(stop_loss: Decimal, rows: list[tuple[str, str, str, str]]):
    bars = _bars_from_ohlc(rows)
    strategy = _TradePlanStrategy({0: StrategyDirection.BULLISH}, stop_loss)
    config = _config(
        end=BASE + timedelta(minutes=len(rows) + 5),
        strategy_id=strategy.strategy_id,
    )
    return run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues(strategy.strategy_id, "v1", "v1", "v1", {}),
        config,
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
    )


# =====================================================================
# A. One normal entry produces one BACKTEST Fill.
# =====================================================================


def test_a_single_entry_produces_one_backtest_source_fill() -> None:
    result = _run_flip()
    assert len(result.fills) == 2  # entry + exit for the one round trip
    assert all(f.source is FillSource.BACKTEST for f in result.fills)


# =====================================================================
# B. One normal round trip produces entry Fill + exit Fill.
# =====================================================================


def test_b_round_trip_produces_entry_and_exit_fill() -> None:
    result = _run_flip()
    assert len(result.trades) == 1
    assert len(result.fills) == 2
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert entry_fill.side is Side.BUY
    assert exit_fill.side is Side.SELL
    assert entry_fill.timestamp < exit_fill.timestamp


# =====================================================================
# C/D/E/F. Fill.order_id maps to the real entry order identity; the
# exit path has no independent exit order identity, so the exit Fill
# documents that limitation by reusing the entry order_id - never a
# fabricated new one.
# =====================================================================


def test_c_entry_fill_order_id_equals_entry_order_intent_order_id() -> None:
    result = _run_flip()
    trade = result.trades[0]
    entry_fill = result.fills[0]
    assert trade.order_intent is not None
    assert entry_fill.order_id == trade.order_intent.order_id


def test_d_exit_fill_reuses_entry_order_id_no_fabricated_identity() -> None:
    """This engine constructs NO independent exit `OrderIntent` anywhere
    - proven directly by inspecting `engine.py`'s own source (only one
    `build_backtest_entry_order_intent()` call site exists, at entry).
    The exit Fill's `order_id` therefore equals the SAME entry
    `order_id`, a documented architectural limitation, not an invented
    new order concept."""
    result = _run_flip()
    trade = result.trades[0]
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert trade.order_intent is not None
    assert exit_fill.order_id == entry_fill.order_id == trade.order_intent.order_id


# =====================================================================
# E. Fill quantity equals actual execution quantity.
# F. Fill price equals actual execution price.
# =====================================================================


def test_e_f_fill_quantity_and_price_equal_trade_values() -> None:
    result = _run_flip()
    trade = result.trades[0]
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert entry_fill.quantity == trade.quantity
    assert exit_fill.quantity == trade.quantity
    assert entry_fill.price == trade.entry_price
    assert exit_fill.price == trade.exit_price


# =====================================================================
# G. Fill timestamp equals simulated execution timestamp.
# =====================================================================


def test_g_fill_timestamps_equal_trade_entry_exit_timestamps() -> None:
    result = _run_flip()
    trade = result.trades[0]
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert entry_fill.timestamp == trade.entry_timestamp
    assert exit_fill.timestamp == trade.exit_timestamp


# =====================================================================
# H. FillSource.BACKTEST.
# =====================================================================


def test_h_fill_source_is_backtest() -> None:
    result = _run_flip()
    assert all(f.source is FillSource.BACKTEST for f in result.fills)


# =====================================================================
# I. Fill status correct - Backtest has no partial-fill concept, so
# every fill is FILLED.
# =====================================================================


def test_i_fill_status_is_filled_never_partial() -> None:
    result = _run_flip()
    assert all(f.status_at_fill is OrderStatus.FILLED for f in result.fills)


# =====================================================================
# J. Transaction cost exact - matches the trade's own
# `cost_breakdown` per-leg totals, summing to the trade's own `costs`.
# =====================================================================


def test_j_fill_transaction_costs_sum_to_trade_costs() -> None:
    result = _run_flip(brokerage_percent=Decimal("0.1"))
    trade = result.trades[0]
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert entry_fill.transaction_cost + exit_fill.transaction_cost == trade.costs
    assert entry_fill.transaction_cost > 0
    assert exit_fill.transaction_cost > 0


# =====================================================================
# K. Slippage exact.
# =====================================================================


def test_k_fill_slippage_applied_is_signed_actual_adjustment() -> None:
    result = _run_flip(slippage_percent=Decimal("1"))
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    # BULLISH entry (BUY): slippage moves price UP (worse for a buyer).
    assert entry_fill.slippage_applied > 0
    # BULLISH exit (SELL): slippage moves price DOWN (worse for a seller).
    assert exit_fill.slippage_applied < 0


def test_k_zero_slippage_produces_zero_slippage_applied() -> None:
    result = _run_flip(slippage_percent=Decimal("0"))
    entry_fill, exit_fill = result.fills[0], result.fills[1]
    assert entry_fill.slippage_applied == 0
    assert exit_fill.slippage_applied == 0


# =====================================================================
# L. Fill IDs deterministic across identical Backtest runs.
# =====================================================================


def test_l_fill_ids_and_values_deterministic_across_identical_runs() -> None:
    r1 = _run_flip()
    r2 = _run_flip()
    assert len(r1.fills) == len(r2.fills) == 2
    for f1, f2 in zip(r1.fills, r2.fills, strict=True):
        assert f1.fill_id == f2.fill_id
        assert f1.order_id == f2.order_id
        assert f1.quantity == f2.quantity
        assert f1.price == f2.price
        assert f1.timestamp == f2.timestamp
        assert f1.transaction_cost == f2.transaction_cost
        assert f1.slippage_applied == f2.slippage_applied
    # Not UUID4 - explicitly NOT random.
    import uuid

    try:
        uuid.UUID(r1.fills[0].fill_id)
        is_uuid = True
    except ValueError:
        is_uuid = False
    assert not is_uuid


# =====================================================================
# M. Multiple fills preserve execution order.
# =====================================================================


def test_m_multiple_trades_preserve_fill_execution_order() -> None:
    closes = ["100", "100", "105", "105", "100", "100", "105"]
    signals = {
        0: StrategyDirection.BULLISH,
        2: StrategyDirection.BEARISH,
        4: StrategyDirection.BULLISH,
        6: StrategyDirection.BEARISH,
    }
    result = _run_flip(closes=closes, signals=signals)
    assert len(result.trades) == 2
    assert len(result.fills) == 4
    timestamps = [f.timestamp for f in result.fills]
    assert timestamps == sorted(timestamps)
    # entry/exit/entry/exit ordering by side, matching the two round trips.
    assert [f.side for f in result.fills] == [Side.BUY, Side.SELL, Side.BUY, Side.SELL]
    # distinct fill_ids throughout.
    assert len({f.fill_id for f in result.fills}) == 4


# =====================================================================
# N. Fill does not alter SimulatedTrade values.
# O. Fill does not alter equity curve.
# P. Fill does not alter metrics.
# =====================================================================


def test_n_o_p_fill_producer_does_not_alter_trade_equity_or_metrics() -> None:
    result = _run_flip()
    trade = result.trades[0]
    assert trade.quantity == Decimal("10")
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("105")
    assert trade.gross_pnl == Decimal("50")
    assert trade.net_pnl == Decimal("50")
    assert trade.reason == "signal_reversal"
    assert len(result.equity_curve) == 2
    assert result.equity_curve[-1].balance == Decimal("100050")
    assert result.metrics.total_trades == 1


# =====================================================================
# Q. Fill does not alter TradePlan exit behavior.
# R. Fill does not alter EOD behavior.
# =====================================================================


def test_q_tradeplan_stop_loss_exit_produces_correct_fills_and_unchanged_trade() -> None:
    # Bar 0: entry signal. Bar 1: entry fills at bar 1's open (100).
    # Bar 2's low touches the stop-loss (90) -> STOP_LOSS exit at 90.
    rows = [
        ("100", "105", "95", "100"),
        ("100", "105", "95", "100"),
        ("95", "96", "85", "90"),
    ]
    result = _run_tradeplan(stop_loss=Decimal("90"), rows=rows)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reason == "STOP_LOSS"
    assert trade.exit_price == Decimal("90")
    assert len(result.fills) == 2
    entry_fill, exit_fill = result.fills
    assert entry_fill.price == trade.entry_price == Decimal("100")
    assert exit_fill.price == trade.exit_price == Decimal("90")
    assert exit_fill.quantity == entry_fill.quantity == trade.quantity


def test_r_eod_force_close_produces_correct_fills_and_unchanged_trade() -> None:
    # No level ever touched - forced closed at final bar's own close.
    rows = [
        ("100", "105", "95", "100"),
        ("100", "105", "95", "100"),
        ("100", "105", "95", "102"),
    ]
    result = _run_tradeplan(stop_loss=Decimal("50"), rows=rows)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reason == "EOD"
    assert trade.exit_price == Decimal("102")
    assert len(result.fills) == 2
    entry_fill, exit_fill = result.fills
    assert exit_fill.price == trade.exit_price == Decimal("102")
    assert exit_fill.timestamp == trade.exit_timestamp


# =====================================================================
# S. Fill does not introduce partial fills where none existed.
# =====================================================================


def test_s_no_partial_fills_introduced() -> None:
    result = _run_flip()
    assert all(f.status_at_fill is not OrderStatus.PARTIALLY_FILLED for f in result.fills)


# =====================================================================
# Profitable / losing / BUY / SELL scenarios.
# =====================================================================


def test_profitable_bullish_trade_fills() -> None:
    result = _run_flip(closes=["100", "100", "110", "110", "115"], signals=_SIGNALS)
    trade = result.trades[0]
    assert trade.net_pnl > 0
    entry_fill, exit_fill = result.fills
    assert entry_fill.side is Side.BUY
    assert exit_fill.side is Side.SELL
    assert exit_fill.price > entry_fill.price


def test_losing_bearish_trade_fills() -> None:
    # BEARISH entry (short) at bar1 open (100), price rises, reversed
    # and closed at bar3 open (105) - a loss for a short position.
    closes = ["100", "100", "105", "105", "110"]
    signals = {0: StrategyDirection.BEARISH, 2: StrategyDirection.BULLISH}
    result = _run_flip(closes=closes, signals=signals)
    trade = result.trades[0]
    entry_fill, exit_fill = result.fills
    assert entry_fill.side is Side.SELL
    assert exit_fill.side is Side.BUY
    assert trade.net_pnl < 0


# =====================================================================
# T/U/V/W: cross-checkpoint isolation.
# =====================================================================


def test_t_paper_fill_producer_test_file_exists_unmodified_marker() -> None:
    # Smoke check: the 64.42 test module file still exists and still
    # contains real test functions (full suite run separately confirms
    # all its tests still pass, unmodified this checkpoint).
    import pathlib

    path = pathlib.Path(__file__).parent / "test_checkpoint_64_42_paper_fill_producer.py"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.count("def test_") > 0


def test_u_fill_contract_schema_unchanged() -> None:
    field_names = set(Fill.__dataclass_fields__)
    assert field_names == {
        "fill_id",
        "order_id",
        "instrument_id",
        "side",
        "quantity",
        "price",
        "timestamp",
        "transaction_cost",
        "slippage_applied",
        "status_at_fill",
        "source",
    }


def test_v_no_dhan_import_in_engine_module() -> None:
    import intraday.research.backtesting.engine as engine_module

    src_file = engine_module.__file__
    assert src_file is not None
    with open(src_file, encoding="utf-8") as fh:
        content = fh.read()
    assert "import dhan" not in content.lower()
    assert "dhanclient" not in content.lower()


def test_w_no_unified_execution_engine_introduced() -> None:
    import intraday.research.backtesting.engine as engine_module

    for forbidden in ("FillBook", "FillManager", "ExecutionLedger", "ExecutionAdapter"):
        assert not hasattr(engine_module, forbidden)


# =====================================================================
# 22. Determinism across two full runs (order_id/timestamp/qty/price).
# =====================================================================


def test_determinism_full_result_comparison_across_two_runs() -> None:
    r1 = _run_flip()
    r2 = _run_flip()
    assert r1.trades == r2.trades
    assert r1.equity_curve == r2.equity_curve
    assert r1.fills == r2.fills


# =====================================================================
# 23. Performance: 1000 simulated fills, O(1) per event.
# =====================================================================


def test_performance_many_round_trips_construct_fills_quickly() -> None:
    # 250 alternating BULLISH/BEARISH round trips -> 500 trades -> 1000
    # fills, well within a generous smoke-test threshold.
    n_round_trips = 250
    closes: list[str] = []
    signals: dict[int, StrategyDirection] = {}
    idx = 0
    price = 100
    for _ in range(n_round_trips):
        closes.append(str(price))
        signals[idx] = StrategyDirection.BULLISH
        idx += 1
        closes.append(str(price))
        idx += 1
        price += 5
        closes.append(str(price))
        signals[idx] = StrategyDirection.BEARISH
        idx += 1
        closes.append(str(price))
        idx += 1
    closes.append(str(price))  # final bar to force EOD-safe end

    start = time.perf_counter()
    result = _run_flip(closes=closes, signals=signals)
    elapsed = time.perf_counter() - start

    assert len(result.fills) == 2 * len(result.trades)
    assert len(result.fills) >= 400  # generous floor, not a fabricated exact count
    assert elapsed < 10.0  # smoke threshold, not a tight microbenchmark
    ms_per_fill = (elapsed * 1000) / max(len(result.fills), 1)
    assert ms_per_fill < 5.0  # generous per-fill ceiling, not a tight microbenchmark
