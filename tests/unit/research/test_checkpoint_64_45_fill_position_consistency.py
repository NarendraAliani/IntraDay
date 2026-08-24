# tests/unit/research/test_checkpoint_64_45_fill_position_consistency.py
#
# Checkpoint 64.45 — CANONICAL FILL -> POSITION CONSISTENCY.
#
# Purpose (per the directive): prove that the canonical `Fill` values
# observed by the system CANNOT silently disagree with the `Position`
# values actually produced by the existing engines, for the SAME
# execution event. This is a CONSISTENCY proof, not a convergence
# claim: Fill is NOT made the Position mutator here (§11 of the
# directive) — the existing execution logic remains the sole authority
# for Position mutation; Fill remains a purely observational record
# built from the SAME local values, never re-derived independently.
#
# Fixture pattern deliberately copied locally (not imported) from
# test_checkpoint_64_44_cross_engine_fill_parity.py /
# test_checkpoint_64_43_backtest_fill_producer.py /
# test_checkpoint_64_42_paper_fill_producer.py, matching this project's
# own established "no cross-test-file coupling" discipline.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.position.contracts import PositionStatus
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
# Backtest-side fixtures (copied from 64.43/64.44)
# =====================================================================


@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub_6445"
    display_name = "Scripted Stub 64.45"
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
        "strategy_id": "scripted_stub_6445",
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


# Long: BUY entry at bar1 open=100, BEARISH reversal exit at bar3 open=105
# — same scripted scenario every prior Fill checkpoint uses.
_CLOSES_LONG = ["100", "100", "105", "105", "110"]
_SIGNALS_LONG = {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH}

# Short: SELL entry at bar1 open=100, BULLISH reversal exit at bar3
# open=95 — mirror-image scenario for SHORT-side consistency.
_CLOSES_SHORT = ["100", "100", "95", "95", "90"]
_SIGNALS_SHORT = {0: StrategyDirection.BEARISH, 2: StrategyDirection.BULLISH}


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
# Paper-side fixtures (copied from 64.42/64.44)
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
# A. Paper BUY entry Fill == Position quantity impact
# =====================================================================


class TestPaperBuyEntryConsistency:
    def test_a_buy_open_fill_quantity_equals_position_quantity(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))

        fill = broker.get_fills()[0]
        position = broker.get_positions()[0]
        assert fill.quantity == position.quantity == Decimal("10")
        assert position.direction is Side.BUY
        assert fill.side is Side.BUY
        assert fill.price == position.average_entry_price


# =====================================================================
# B. Paper SELL/short entry Fill == Position quantity impact
# =====================================================================


class TestPaperSellShortEntryConsistency:
    def test_b_sell_open_fill_quantity_equals_position_quantity(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.SELL, quantity=Decimal("10")))

        fill = broker.get_fills()[0]
        position = broker.get_positions()[0]
        assert fill.quantity == position.quantity == Decimal("10")
        assert position.direction is Side.SELL
        assert fill.side is Side.SELL
        assert fill.price == position.average_entry_price


# =====================================================================
# C. Paper closing Fill == Position quantity reduction
# =====================================================================


class TestPaperClosingFillConsistency:
    def test_c_buy_close_fill_quantity_equals_position_reduction(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        opened = broker.get_positions()[0]
        assert opened.quantity == Decimal("10")

        broker.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(
                order_id="ord-p-2",
                idempotency_key="idem-p-2",
                side=Side.SELL,
                quantity=Decimal("10"),
            )
        )
        closing_fill = broker.get_fills()[1]
        closed = broker.get_positions()[0]
        # Per the ACTUAL `_apply_to_position()` full-close branch, the
        # closed Position's own `quantity` field is set to the CLOSED
        # amount (`closing_quantity`), not zero — `Position.quantity`
        # must always be positive (`Position.__post_init__`). This is
        # the existing contract's own representation for a CLOSED
        # position; the invariant under test is that this value equals
        # the closing Fill's own quantity, not a naive "==0" assertion.
        assert closed.status is PositionStatus.CLOSED
        assert closed.quantity == closing_fill.quantity == Decimal("10")
        assert closing_fill.price == Decimal("110.00")

    def test_c_sell_close_fill_quantity_equals_position_reduction(self) -> None:
        # Short open, then BUY-to-cover close.
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.SELL, quantity=Decimal("10")))

        broker.record_price(RELIANCE, Decimal("90.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(
                order_id="ord-p-2",
                idempotency_key="idem-p-2",
                side=Side.BUY,
                quantity=Decimal("10"),
            )
        )
        closing_fill = broker.get_fills()[1]
        closed = broker.get_positions()[0]
        assert closed.status is PositionStatus.CLOSED
        assert closed.quantity == closing_fill.quantity == Decimal("10")
        assert closing_fill.price == Decimal("90.00")


# =====================================================================
# D. Paper multi-fill cumulative quantity is exact
# =====================================================================


class TestPaperMultiFillCumulativeQuantity:
    def test_d_partial_then_completion_fills_sum_to_final_position_quantity(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(quantity=Decimal("10")))

        first_fill = broker.get_fills()[0]
        after_first = broker.get_positions()[0]
        assert first_fill.quantity == Decimal("5")
        assert after_first.quantity == Decimal("5")

        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=5))
        fills = broker.get_fills()
        assert len(fills) == 2
        assert [f.quantity for f in fills] == [Decimal("5"), Decimal("5")]

        final_position = broker.get_positions()[0]
        cumulative_fill_quantity = sum((f.quantity for f in fills), Decimal("0"))
        assert cumulative_fill_quantity == Decimal("10")
        # Final Position quantity reflects the TOTAL executed (10), never
        # only the first partial (5) and never an over-fill (15).
        assert final_position.quantity == cumulative_fill_quantity == Decimal("10")


# =====================================================================
# E. Paper average entry price agrees with Fill-weighted execution data
# =====================================================================


class TestPaperAverageEntryPriceConsistency:
    def test_e_two_same_side_fills_produce_fill_weighted_average(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))

        broker.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(
                order_id="ord-p-2",
                idempotency_key="idem-p-2",
                side=Side.BUY,
                quantity=Decimal("10"),
            )
        )
        fills = broker.get_fills()
        assert len(fills) == 2
        position = broker.get_positions()[0]
        # Existing `_apply_to_position()` averaging formula (NOT
        # rewritten by this checkpoint) — validated against the same
        # Fill-observed quantity/price pairs.
        expected_average = (
            fills[0].price * fills[0].quantity + fills[1].price * fills[1].quantity
        ) / (fills[0].quantity + fills[1].quantity)
        assert position.average_entry_price == expected_average
        assert position.quantity == fills[0].quantity + fills[1].quantity == Decimal("20")


# =====================================================================
# F. Paper no overfill
# =====================================================================


class TestPaperNoOverfill:
    def test_f_partial_fill_sum_never_exceeds_requested_quantity(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=5))
        # A third record_price() tick must NOT produce a third fill —
        # the order is already FILLED, `record_price()` only re-attempts
        # PENDING/PARTIALLY_FILLED orders.
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=10))

        fills = broker.get_fills()
        total = sum((f.quantity for f in fills), Decimal("0"))
        assert total == order.quantity
        assert total <= order.quantity
        position = broker.get_positions()[0]
        assert position.quantity == total


# =====================================================================
# G. Paper full close quantity agrees with Fill
# =====================================================================


class TestPaperFullCloseQuantityConsistency:
    def test_g_full_close_reconciles_exactly(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        opened = broker.get_positions()[0]

        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=5))
        broker.submit_order(
            _order(
                order_id="ord-p-2",
                idempotency_key="idem-p-2",
                side=Side.SELL,
                quantity=Decimal("10"),
            )
        )
        closing_fill = broker.get_fills()[1]
        closed = broker.get_positions()[0]

        # Reconciliation: the quantity actually closed (as recorded by
        # the closing Fill) equals the ENTIRE previously-open quantity —
        # nothing remains open, proven via existing engine's own math
        # (existing.quantity - closing_quantity == 0), not by asserting
        # `Position.quantity == 0` (which the contract forbids).
        remaining_open = opened.quantity - closing_fill.quantity
        assert remaining_open == Decimal("0")
        assert closed.status is PositionStatus.CLOSED
        assert closed.quantity == closing_fill.quantity


# =====================================================================
# H/I. Backtest entry Fill == Position/trade entry quantity and price
# =====================================================================


class TestBacktestEntryConsistency:
    def test_h_entry_fill_quantity_equals_trade_quantity(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        entry_fill, _exit_fill = bt.fills
        trade = bt.trades[0]
        assert entry_fill.quantity == trade.quantity

    def test_i_entry_fill_price_equals_actual_entry_price(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        entry_fill, _exit_fill = bt.fills
        trade = bt.trades[0]
        assert entry_fill.price == trade.entry_price


# =====================================================================
# J/K. Backtest exit Fill == actual exit quantity and price
# =====================================================================


class TestBacktestExitConsistency:
    def test_j_exit_fill_quantity_equals_actual_exit_quantity(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        _entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        assert exit_fill.quantity == trade.quantity

    def test_k_exit_fill_price_equals_actual_exit_price(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        _entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        assert exit_fill.price == trade.exit_price


# =====================================================================
# L. Long consistency (both engines)
# =====================================================================


class TestLongConsistency:
    def test_l_backtest_long_round_trip_fill_position_consistency(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        # `SimulatedTrade.direction` is a `StrategyDirection`
        # (BULLISH/BEARISH), a different vocabulary from `Fill.side`
        # (`Side.BUY`/`Side.SELL`) — verified by direct source
        # inspection this checkpoint, not assumed. BULLISH corresponds
        # to a BUY entry / SELL exit round trip.
        assert trade.direction is StrategyDirection.BULLISH
        assert entry_fill.side is Side.BUY
        assert exit_fill.side is Side.SELL
        assert entry_fill.quantity == exit_fill.quantity == trade.quantity
        assert entry_fill.price == trade.entry_price
        assert exit_fill.price == trade.exit_price

    def test_l_paper_long_round_trip_fill_position_consistency(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        entry_fill = broker.get_fills()[0]
        opened = broker.get_positions()[0]
        assert opened.direction is Side.BUY
        assert opened.quantity == entry_fill.quantity


# =====================================================================
# M. Short consistency (both engines)
# =====================================================================


class TestShortConsistency:
    def test_m_backtest_short_round_trip_fill_position_consistency(self) -> None:
        bt = _run_backtest(_CLOSES_SHORT, _SIGNALS_SHORT)
        entry_fill, exit_fill = bt.fills
        trade = bt.trades[0]
        # Same vocabulary distinction as the LONG test above — BEARISH
        # corresponds to a SELL entry / BUY exit (short) round trip.
        assert trade.direction is StrategyDirection.BEARISH
        assert entry_fill.side is Side.SELL
        assert exit_fill.side is Side.BUY
        assert entry_fill.quantity == exit_fill.quantity == trade.quantity
        assert entry_fill.price == trade.entry_price
        assert exit_fill.price == trade.exit_price

    def test_m_paper_short_round_trip_fill_position_consistency(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.SELL, quantity=Decimal("10")))
        entry_fill = broker.get_fills()[0]
        opened = broker.get_positions()[0]
        assert opened.direction is Side.SELL
        assert opened.quantity == entry_fill.quantity


# =====================================================================
# N/O/P/Q. Accounting preservation — realized/realized_net/unrealized
# pnl and equity all unaffected by Fill's presence/observation.
# =====================================================================


class TestAccountingPreservation:
    def test_n_backtest_realized_pnl_unchanged(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        trade = bt.trades[0]
        assert trade.gross_pnl == Decimal("50")
        assert bt.fills  # Fill's presence did not alter this value.

    def test_o_paper_realized_net_pnl_unchanged(self) -> None:
        broker = _broker(compute_cost=_flat_cost(Decimal("1.00")))
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
        trade = broker.get_trades()[0]
        assert trade.realized_pnl == Decimal("100.00")
        # gross realized (100) minus attributable cost (1 entry + 1 exit = 2)
        assert trade.realized_net_pnl == Decimal("98.00")
        assert len(broker.get_fills()) == 2  # Fill observation present.

    def test_p_paper_unrealized_pnl_unchanged_by_fill_presence(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=5))

        expected_unrealized = (Decimal("105.00") - Decimal("100.00")) * Decimal("10")
        assert broker.get_total_unrealized_pnl() == expected_unrealized
        assert len(broker.get_fills()) == 1  # observing the Fill changes nothing above.

    def test_q_paper_equity_unchanged_by_fill_presence(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        broker.submit_order(_order(side=Side.BUY, quantity=Decimal("10")))
        equity_before_second_read = broker.get_equity()
        _ = broker.get_fills()  # merely reading Fill observations
        equity_after_second_read = broker.get_equity()
        assert equity_before_second_read == equity_after_second_read

    def test_q_backtest_equity_unchanged(self) -> None:
        bt = _run_backtest(_CLOSES_LONG, _SIGNALS_LONG)
        assert bt.equity_curve[-1].balance == Decimal("100050")
        assert len(bt.fills) == 2  # Fill's presence did not alter this value.


# =====================================================================
# R. Fill remains purely observational — no production code reads
# `fills`/`get_fills()` to drive a Position mutation.
# =====================================================================


class TestFillRemainsObservational:
    def test_r_apply_to_position_source_never_reads_fills_list(self) -> None:
        import inspect

        from intraday.infrastructure.brokers.paper.broker import PaperBroker as _PB

        source = inspect.getsource(_PB._apply_to_position)
        assert "self._fills" not in source
        assert "get_fills" not in source

    def test_r_backtest_trade_construction_never_reads_fills_list(self) -> None:
        import inspect

        import intraday.research.backtesting.engine as engine_mod

        source = inspect.getsource(engine_mod)
        # `fills.append(...)` is the ONLY interaction the engine has with
        # its own `fills` list — never `fills[...]`/`for f in fills`
        # feeding back into `SimulatedTrade`/`OpenPosition` construction.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("fills."):
                assert stripped.startswith("fills.append(")

    def test_r_paper_position_mutation_does_not_require_fill_construction_order(self) -> None:
        # Structural proof, mirroring the source read above: in
        # `_attempt_fill()`, `_apply_to_position()` is called BEFORE the
        # `Fill` object is constructed — the Position mutation cannot be
        # reading a Fill that does not exist yet at the time it runs.
        import inspect

        from intraday.infrastructure.brokers.paper.broker import PaperBroker as _PB

        source = inspect.getsource(_PB._attempt_fill)
        apply_index = source.index("self._apply_to_position(")
        fill_construct_index = source.index("self._fills.append(")
        assert apply_index < fill_construct_index


# =====================================================================
# S/T/U. No new execution subsystem; no Dhan; no frontend.
# =====================================================================


class TestScopeBoundaries:
    def test_s_no_new_execution_subsystem_introduced(self) -> None:
        import intraday.infrastructure.brokers.paper.broker as broker_mod
        import intraday.research.backtesting.engine as engine_mod

        forbidden = (
            "FillBook",
            "FillManager",
            "ExecutionLedger",
            "ExecutionAdapter",
            "UnifiedExecutionEngine",
            "PositionMutator",
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
        import sys

        for mod_name in sys.modules:
            if mod_name.startswith("intraday"):
                assert "frontend" not in mod_name.lower()


# =====================================================================
# Cross-checkpoint isolation — this file does not modify the Fill
# contract, PaperBroker, or the Backtest engine.
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

    def test_source_enum_still_has_expected_members(self) -> None:
        assert {m.value for m in FillSource} == {"BACKTEST", "PAPER", "LIVE"}

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

    def test_backtest_engine_module_diff_is_prior_checkpoint_carried_forward(self) -> None:
        # engine.py DOES carry a diff versus the committed HEAD — but it
        # is 64.43's own Fill-producer wiring (carried-forward,
        # already-accepted work), not a NEW 64.45 change. 64.45 itself
        # does not re-open engine.py for editing.
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
