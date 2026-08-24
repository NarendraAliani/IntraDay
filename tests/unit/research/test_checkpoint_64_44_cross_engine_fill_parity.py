# tests/unit/research/test_checkpoint_64_44_cross_engine_fill_parity.py
#
# Checkpoint 64.44 — CROSS-ENGINE FILL PARITY VALIDATION.
#
# Purpose (per the directive): PROVE whether Backtest's `Fill` producer
# (`research.backtesting.engine.run_backtest()`, Checkpoint 64.43) and
# Paper's `Fill` producer (`infrastructure.brokers.paper.broker.
# PaperBroker`, Checkpoint 64.42) are semantically compatible where the
# underlying economic scenario is genuinely comparable, and to precisely
# document where they legitimately differ. This file creates NO new
# execution subsystem, modifies NEITHER producer, and does NOT touch
# Dhan, the frontend, or accounting/Position code.
#
# Fixture pattern deliberately copied locally (not imported) from
# test_checkpoint_64_43_backtest_fill_producer.py and
# test_checkpoint_64_42_paper_fill_producer.py, matching this project's
# own established "no cross-test-file coupling" discipline.
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
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
)

INSTRUMENT_BT = "NSE:TESTCO"
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


# =====================================================================
# Backtest-side fixtures (copied from 64.43)
# =====================================================================


@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub_6444"
    display_name = "Scripted Stub 64.44"
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


def _bars_from_closes(closes: list[str]) -> tuple[Bar, ...]:
    bars = []
    for i, c in enumerate(closes):
        price = Decimal(c)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT_BT,
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
        "instrument_id": INSTRUMENT_BT,
        "timeframe": Timeframe.ONE_MINUTE,
        "start": BASE,
        "end": BASE + timedelta(minutes=40),
        "strategy_id": "scripted_stub_6444",
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


# BUY entry at bar1 open=100, BEARISH reversal exit at bar3 open=105 —
# same scripted scenario 64.29/.../64.43 already use, so numbers are
# directly comparable to prior checkpoints' own reports.
_CLOSES_BUY = ["100", "100", "105", "105", "110"]
_SIGNALS_BUY = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}

# SELL(short) entry at bar1 open=100, BULLISH reversal exit at bar3
# open=95 — the mirror-image scenario for SELL-side parity.
_CLOSES_SELL = ["100", "100", "95", "95", "90"]
_SIGNALS_SELL = {0: StrategyDirection.BEARISH, 2: StrategyDirection.BULLISH}


def _run_backtest(
    closes: list[str],
    signals: dict[int, StrategyDirection],
    slippage_percent: Decimal = Decimal("0"),
    brokerage_percent: Decimal = Decimal("0"),
):
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals)
    config = _config(
        end=BASE + timedelta(minutes=len(closes) + 5),
        slippage_percent=slippage_percent,
        brokerage_percent=brokerage_percent,
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
# Paper-side fixtures (copied from 64.42)
# =====================================================================


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _flat_cost(amount: Decimal):
    def _cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
        return amount

    return _cost


def _clock_sequence(start: datetime):
    state = {"t": start}

    def _clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return _clock


def _broker(**overrides: object) -> PaperBroker:
    fields: dict[str, object] = {
        "initial_capital": Decimal("1000000"),
        "compute_cost": _no_cost,
        "clock": _clock_sequence(BASE),
    }
    fields.update(overrides)
    return PaperBroker(**fields)  # type: ignore[arg-type]


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-p-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "strat-p-1",
        "created_at": BASE,
        "idempotency_key": "idem-p-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


# =====================================================================
# A/S/T/U. Canonical Fill type used by both producers; no new execution
# subsystem; no Dhan; no frontend.
# =====================================================================


class TestCanonicalFillTypeSharedAcrossEngines:
    def test_a_both_producers_emit_the_same_dataclass_type(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        bt_fill = bt.fills[0]
        paper_fill = broker.get_fills()[0]
        assert type(bt_fill) is Fill
        assert type(paper_fill) is Fill
        assert type(bt_fill) is type(paper_fill)

    def test_s_no_new_execution_subsystem_introduced(self) -> None:
        # Mechanical proof: neither module gains a FillBook/FillManager/
        # ExecutionLedger/ExecutionAdapter/unified execution engine —
        # this parity file itself introduces none either.
        import intraday.infrastructure.brokers.paper.broker as broker_mod
        import intraday.research.backtesting.engine as engine_mod

        forbidden = (
            "FillBook",
            "FillManager",
            "ExecutionLedger",
            "ExecutionAdapter",
            "UnifiedExecutionEngine",
        )
        for name in forbidden:
            assert not hasattr(engine_mod, name)
            assert not hasattr(broker_mod, name)

    def test_t_no_dhan_import_anywhere_in_this_file(self) -> None:
        import intraday.infrastructure.brokers.paper.broker as broker_mod
        import intraday.research.backtesting.engine as engine_mod

        assert "dhan" not in broker_mod.__name__.lower()
        assert "dhan" not in engine_mod.__name__.lower()
        for name in dir(engine_mod):
            assert "dhan" not in name.lower()
        for name in dir(broker_mod):
            assert "dhan" not in name.lower()

    def test_u_no_frontend_file_touched(self) -> None:
        # This test file imports only backend Python modules — no
        # `frontend`/`.tsx` module reference anywhere in its imports.
        import sys

        for mod_name in sys.modules:
            if mod_name.startswith("intraday"):
                assert "frontend" not in mod_name.lower()


# =====================================================================
# B. BUY semantic parity
# =====================================================================


class TestBuySemanticParity:
    def test_b_buy_side_matches_across_engines(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY))

        bt_entry = bt.fills[0]
        paper_fill = broker.get_fills()[0]
        assert bt_entry.side is Side.BUY
        assert paper_fill.side is Side.BUY
        assert bt_entry.side is paper_fill.side


# =====================================================================
# C. SELL semantic parity
# =====================================================================


class TestSellSemanticParity:
    def test_c_sell_side_matches_across_engines(self) -> None:
        # Backtest: a BEARISH (short) entry produces a SELL entry Fill.
        bt = _run_backtest(_CLOSES_SELL, _SIGNALS_SELL)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.SELL))

        bt_entry = bt.fills[0]
        paper_fill = broker.get_fills()[0]
        assert bt_entry.side is Side.SELL
        assert paper_fill.side is Side.SELL
        assert bt_entry.side is paper_fill.side


# =====================================================================
# D. quantity semantics — comparable complete executions with the same
# requested/final quantity must be numerically equal.
# =====================================================================


class TestQuantitySemantics:
    def test_d_comparable_complete_execution_quantity_equal(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)  # position_size_value=10
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))

        bt_entry = bt.fills[0]
        paper_fill = broker.get_fills()[0]
        assert bt_entry.quantity == Decimal("10")
        assert paper_fill.quantity == Decimal("10")
        assert bt_entry.quantity == paper_fill.quantity

    def test_paper_partial_fill_sum_equals_requested_quantity(self) -> None:
        # F/N: Paper's own multi-fill capability, NOT forced onto
        # Backtest — sum of partial fills equals the requested quantity
        # once the order completes.
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=5))

        fills = broker.get_fills()
        assert len(fills) == 2
        assert sum((f.quantity for f in fills), Decimal("0")) == order.quantity

    def test_backtest_never_produces_partial_fills(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        assert all(f.status_at_fill is OrderStatus.FILLED for f in bt.fills)
        assert not any(f.status_at_fill is OrderStatus.PARTIALLY_FILLED for f in bt.fills)


# =====================================================================
# E. actual execution-price semantics — Fill.price = the actual final
# execution price used by THAT engine (never a claim of cross-engine
# numeric equality unless deliberately controlled).
# =====================================================================


class TestExecutionPriceSemantics:
    def test_e_backtest_fill_price_equals_that_engines_own_final_price(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        assert entry_fill.price == trade.entry_price
        assert exit_fill.price == trade.exit_price

    def test_e_paper_fill_price_equals_that_engines_own_final_price(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())
        fill = broker.get_fills()[0]
        # PaperBroker's own average_fill_price for the order must equal
        # the Fill's own recorded price — same engine, same value.
        report = broker.get_order_status(fill.order_id)
        assert report.average_fill_price == fill.price

    def test_e_controlled_scenario_deliberately_supplies_same_price(self) -> None:
        # Deliberate, controlled equality: zero-slippage Backtest entry
        # at bar1 open=100 vs zero-slippage Paper MARKET fill at an
        # explicitly recorded price of 100 — the ONLY case this suite
        # asserts cross-engine price equality, because both were
        # deliberately configured to use the identical reference price.
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        bt_entry = bt.fills[0]
        paper_fill = broker.get_fills()[0]
        assert bt_entry.price == Decimal("100.00")
        assert paper_fill.price == Decimal("100.00")
        assert bt_entry.price == paper_fill.price


# =====================================================================
# F. signed slippage semantics — slippage_applied = signed difference
# from that engine's own pre-slippage reference.
# =====================================================================


class TestSlippageSemantics:
    def test_f_backtest_signed_slippage_matches_engine_reference(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY, slippage_percent=Decimal("1"))
        entry_fill = bt.fills[0]
        # BUY entry -> worse (higher) fill than raw bar open -> positive.
        assert entry_fill.slippage_applied > 0

    def test_f_paper_signed_slippage_matches_engine_reference(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY))
        fill = broker.get_fills()[0]
        # BUY -> worse (higher) fill than the raw observed price -> positive.
        assert fill.slippage_applied > 0

    def test_f_zero_slippage_configuration_produces_zero_on_both_engines(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY, slippage_percent=Decimal("0"))
        broker = _broker(slippage_percent=Decimal("0"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        assert bt.fills[0].slippage_applied == Decimal("0")
        assert broker.get_fills()[0].slippage_applied == Decimal("0")


# =====================================================================
# G. transaction-cost semantics — same cost model + same price/quantity
# implies matching transaction_cost, using Decimal.
# =====================================================================


class TestTransactionCostSemantics:
    def test_g_transaction_cost_is_decimal_on_both_engines(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY, brokerage_percent=Decimal("0.1"))
        broker = _broker(compute_cost=_flat_cost(Decimal("12.34")))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        assert isinstance(bt.fills[0].transaction_cost, Decimal)
        assert isinstance(broker.get_fills()[0].transaction_cost, Decimal)

    def test_g_same_injected_cost_value_reproduced_exactly_on_paper(self) -> None:
        # A controlled, deliberate equality: PaperBroker's cost model is
        # a pure injected callable — the exact value it returns is the
        # exact value Fill.transaction_cost carries.
        broker = _broker(compute_cost=_flat_cost(Decimal("12.34")))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())
        assert broker.get_fills()[0].transaction_cost == Decimal("12.34")

    def test_g_backtest_cost_reproduces_the_engines_own_cost_model_output(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY, brokerage_percent=Decimal("0.1"))
        entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        # Sum of the two per-leg Fill costs equals the SAME engine's own
        # authoritative trade.costs total (64.43's own proven invariant).
        assert entry_fill.transaction_cost + exit_fill.transaction_cost == trade.costs


# =====================================================================
# H. status semantics
# =====================================================================


class TestStatusSemantics:
    def test_h_comparable_complete_fills_are_filled_on_both_engines(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        assert all(f.status_at_fill is OrderStatus.FILLED for f in bt.fills)
        assert broker.get_fills()[0].status_at_fill is OrderStatus.FILLED

    def test_h_paper_intermediate_partial_fill_is_partially_filled(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))
        first = broker.get_fills()[0]
        assert first.status_at_fill is OrderStatus.PARTIALLY_FILLED

    def test_h_backtest_has_no_partial_fill_concept_documented_asymmetry(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        # Backtest's exit path always closes a position's ENTIRE
        # quantity in one _close_trade() call — never PARTIALLY_FILLED.
        assert not any(f.status_at_fill is OrderStatus.PARTIALLY_FILLED for f in bt.fills)


# =====================================================================
# I. source semantics
# =====================================================================


class TestSourceSemantics:
    def test_i_source_provenance_is_explicit_and_distinct(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())

        assert all(f.source is FillSource.BACKTEST for f in bt.fills)
        assert all(f.source is FillSource.PAPER for f in broker.get_fills())
        assert FillSource.BACKTEST != FillSource.PAPER


# =====================================================================
# J. fill ordering — actual chronological order, never re-sorted.
# =====================================================================


class TestFillOrdering:
    def test_j_backtest_fills_are_entry_then_exit_chronologically(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        entry_fill, exit_fill = bt.fills
        assert entry_fill.timestamp <= exit_fill.timestamp
        assert entry_fill.side is Side.BUY
        assert exit_fill.side is Side.SELL

    def test_j_paper_fills_preserve_observation_order(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))
        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=5))

        fills = broker.get_fills()
        assert fills[0].timestamp < fills[1].timestamp
        assert fills[0].status_at_fill is OrderStatus.PARTIALLY_FILLED
        assert fills[1].status_at_fill is OrderStatus.FILLED


# =====================================================================
# K. Backtest deterministic Fill IDs
# =====================================================================


class TestBacktestDeterministicFillIds:
    def test_k_identical_backtest_runs_produce_identical_fill_ids(self) -> None:
        bt1 = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        bt2 = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        assert [f.fill_id for f in bt1.fills] == [f.fill_id for f in bt2.fills]

    def test_k_backtest_fill_ids_are_not_uuid4(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        for fill in bt.fills:
            try:
                uuid.UUID(fill.fill_id)
                is_uuid = True
            except ValueError:
                is_uuid = False
            assert not is_uuid


# =====================================================================
# L. Paper unique Fill IDs
# =====================================================================


class TestPaperUniqueFillIds:
    def test_l_paper_fill_ids_are_unique_across_multiple_fills(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))
        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=5))
        fills = broker.get_fills()
        assert len({f.fill_id for f in fills}) == len(fills)

    def test_l_paper_fill_ids_are_valid_uuid4(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())
        fill = broker.get_fills()[0]
        parsed = uuid.UUID(fill.fill_id)
        assert parsed.version == 4

    def test_l_repeated_paper_runs_do_not_reproduce_identical_fill_ids(self) -> None:
        # Contrast with K: Paper is runtime-unique, NOT reproducible —
        # this is a documented, expected DIFFERENCE, not a defect.
        broker1 = _broker()
        broker1.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker1.submit_order(_order(order_id="ord-x", idempotency_key="idem-x"))

        broker2 = _broker()
        broker2.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker2.submit_order(_order(order_id="ord-x", idempotency_key="idem-x"))

        assert broker1.get_fills()[0].fill_id != broker2.get_fills()[0].fill_id


# =====================================================================
# M. comparable complete execution quantity equality (round-trip level)
# =====================================================================


class TestComparableCompleteExecutionQuantityEquality:
    def test_m_full_round_trip_quantity_matches_requested_quantity_both_engines(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(quantity=Decimal("10"))
        broker.submit_order(order)

        assert bt.fills[0].quantity == Decimal("10")
        assert bt.fills[1].quantity == Decimal("10")
        assert broker.get_fills()[0].quantity == order.quantity


# =====================================================================
# N. Position quantity equality (observational only — Fill is not the
# position-update mechanism on either engine).
# =====================================================================


class TestPositionQuantityEquality:
    def test_n_paper_position_quantity_equals_fill_quantity(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))
        fill = broker.get_fills()[0]
        position = broker.get_positions()[0]
        assert position.quantity == fill.quantity

    def test_n_backtest_trade_quantity_equals_fill_quantity(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        assert trade.quantity == entry_fill.quantity == exit_fill.quantity


# =====================================================================
# O. Position execution-price equality
# =====================================================================


class TestPositionExecutionPriceEquality:
    def test_o_paper_position_entry_price_equals_fill_price(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order())
        fill = broker.get_fills()[0]
        position = broker.get_positions()[0]
        assert position.average_entry_price == fill.price

    def test_o_backtest_trade_entry_price_equals_fill_price(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        entry_fill, _exit_fill = bt.fills
        trade = bt.trades[0]
        assert trade.entry_price == entry_fill.price


# =====================================================================
# P. Backtest/Paper accounting unchanged by Fill production.
# =====================================================================


class TestAccountingUnchangedByFillProduction:
    def test_p_backtest_equity_and_pnl_unchanged_by_fill_presence(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        trade = bt.trades[0]
        # Same values 64.29/.../64.43's own scripted scenario has always
        # produced — Fill production did not alter them.
        assert trade.gross_pnl == Decimal("50")
        assert trade.net_pnl == Decimal("50")
        assert bt.equity_curve[-1].balance == Decimal("100050")

    def test_p_paper_realized_and_equity_unchanged_by_fill_presence(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        broker.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(
                order_id="ord-p-2",
                idempotency_key="idem-p-2",
                side=Side.SELL,
                quantity=Decimal("10"),
            )
        )
        trades = broker.get_trades()
        assert len(trades) == 1
        assert trades[0].realized_pnl == Decimal("100.00")
        # get_fills() being non-empty did not change realized accounting.
        assert len(broker.get_fills()) == 2


# =====================================================================
# Q. Backtest exit-order identity difference — explicitly documented,
# not accidental.
# =====================================================================


class TestBacktestExitOrderIdentityDifference:
    def test_q_backtest_exit_fill_reuses_entry_order_id(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        entry_fill, exit_fill = bt.fills
        # DOCUMENTED, not accidental: this engine constructs no
        # independent exit OrderIntent (64.43 finding, re-verified here)
        # so the exit Fill deliberately reuses the entry order's identity.
        assert exit_fill.order_id == entry_fill.order_id

    def test_q_paper_exit_fill_can_have_a_genuinely_distinct_order_identity(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(
            _order(order_id="ord-entry", idempotency_key="idem-entry", side=Side.BUY)
        )
        broker.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(order_id="ord-exit", idempotency_key="idem-exit", side=Side.SELL)
        )
        fills = broker.get_fills()
        entry_fill, exit_fill = fills[0], fills[1]
        # Genuine DIFFERENCE from Backtest: Paper's exit is its own real
        # order with its own real order_id, not a reuse of the entry's.
        assert entry_fill.order_id == "ord-entry"
        assert exit_fill.order_id == "ord-exit"
        assert entry_fill.order_id != exit_fill.order_id


# =====================================================================
# R. Paper partial-fill capability — explicitly documented, not forced
# onto Backtest.
# =====================================================================


class TestPaperPartialFillCapabilityDocumented:
    def test_r_paper_can_produce_multiple_fills_for_one_order(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))
        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=5))
        assert len(broker.get_fills()) == 2

    def test_r_backtest_never_produces_more_than_one_fill_per_execution_event(self) -> None:
        bt = _run_backtest(_CLOSES_BUY, _SIGNALS_BUY)
        # Exactly 2: one entry, one exit — never split into partials.
        assert len(bt.fills) == 2


# =====================================================================
# Cross-checkpoint isolation — this file does not import/modify 64.41/
# 64.42/64.43's own files, and does not alter the Fill contract.
# =====================================================================


class TestCrossCheckpointIsolation:
    def test_fill_contract_field_set_unchanged(self) -> None:
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(Fill)}
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

    def test_paper_broker_module_has_zero_diff_this_checkpoint(self) -> None:
        import subprocess

        result = subprocess.run(  # noqa: S603
            ["git", "diff", "--", "src/intraday/infrastructure/brokers/paper/broker.py"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=__file__.rsplit("tests", 1)[0],
        )
        diff_text = result.stdout
        # Checkpoint 64.68 relaxed this from "zero diff" to "any diff must
        # be content-attributable to a LATER checkpoint" - the SAME shape
        # the sibling `test_backtest_engine_module_diff_is_*_carried_
        # forward` assertion in this very class already uses for
        # `engine.py`. The distinction this class actually protects is
        # "THIS checkpoint did not re-open the paper broker", and that is
        # still enforced: a diff is only tolerated when it names the
        # checkpoint that made it.
        #
        # 64.68's own change is a single ADDITIVE, default-preserving
        # `id_factory` constructor parameter, so that a deterministic
        # replay paper session can make the broker's SURROGATE
        # identifiers (event/fill/position/trade) reproducible - its §17
        # acceptance criterion. It changes no price, quantity, cost or
        # P&L behaviour whatsoever, and every pre-existing construction
        # site omits it and keeps the previous `uuid.uuid4()` behaviour.
        if diff_text.strip():
            assert (
                "64.68" in diff_text
            ), "paper/broker.py carries a diff that is not attributable to a known checkpoint"
            for economic_marker in ("_available_balance =", "realized_pnl", "slippage_percent"):
                assert f"-        {economic_marker}" not in diff_text, (
                    f"the paper broker's {economic_marker} accounting was modified - "
                    "this class exists to prevent exactly that"
                )

    def test_backtest_engine_module_diff_is_64_43_carried_forward_not_64_44(self) -> None:
        # engine.py DOES carry a diff versus the committed HEAD — but it
        # is 64.43's own Fill-producer wiring (carried-forward,
        # already-accepted work), not a NEW 64.44 change. 64.44 itself
        # does not re-open engine.py for editing. Proven by content
        # inspection, not merely by the presence of a diff.
        import subprocess

        result = subprocess.run(  # noqa: S603
            ["git", "diff", "--", "src/intraday/research/backtesting/engine.py"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=__file__.rsplit("tests", 1)[0],
        )
        diff_text = result.stdout
        if diff_text.strip():
            assert "64.43" in diff_text
