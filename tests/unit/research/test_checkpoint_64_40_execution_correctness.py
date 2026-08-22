# tests/unit/research/test_checkpoint_64_40_execution_correctness.py
#
# Checkpoint 64.40 — FIX EXECUTION CORRECTNESS FINDINGS F1 + F2 AND
# CENTRALIZE SLIPPAGE SEMANTICS. Directly targets the two genuine
# execution defects Checkpoint 64.39 proved (F1: a partially-filled
# MARKET order had no code path to complete its remainder; F2: a
# crossed LIMIT order's slippage could push the fill worse than the
# stated limit price) and proves the ONE new shared slippage function
# is actually called by both Backtest's `CostModel` and Paper's
# `PaperBroker` (not merely structurally similar, independently
# maintained code).
#
# Deliberately does NOT introduce a `Fill` contract, an execution
# engine, or a partial-exit engine (see the checkpoint 64.40 directive).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.domain.shared_kernel.slippage import apply_flat_percentage_slippage
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.research.backtesting import StrategyDirection
from intraday.research.backtesting.cost_model import (
    FlatPercentageCostModel,
    IndianCashEquityIntradayCostModel,
    verified_nse_cash_equity_intraday_cost_model,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _clock_sequence(start: datetime):  # type: ignore[no-untyped-def]
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
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "strat-1",
        "created_at": BASE,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


# ============================================================
# F1 — partial MARKET fill completion
# ============================================================


class TestF1PartialMarketFillCompletes:
    """Section 6/20 A-F of the 64.40 directive: a MARKET order left
    PARTIALLY_FILLED (via `partial_fill_ratio < 1`) must complete its
    remaining quantity on the next valid `record_price()` observation,
    reach FILLED, never exceed the requested quantity, and
    `partial_fill_ratio = 1` must remain ordinary full-fill behavior."""

    def test_multi_fill_completes_to_exact_quantity_and_status_filled(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        first = broker.get_order_status(order.order_id)
        assert first.status is OrderStatus.PARTIALLY_FILLED
        assert first.filled_quantity == Decimal("5")

        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=2))
        second = broker.get_order_status(order.order_id)
        assert second.status is OrderStatus.FILLED
        assert second.filled_quantity == Decimal("10.00")
        assert order.quantity - second.filled_quantity == Decimal("0.00")

        # Position quantity reflects cumulative fills exactly - no
        # quantity created or destroyed.
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("10.00")

    def test_cost_computed_per_fill_and_summed_correctly(self) -> None:
        calls: list[Decimal] = []

        def _tracking_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
            calls.append(notional)
            return Decimal("1.00")

        broker = _broker(partial_fill_ratio=Decimal("0.5"), compute_cost=_tracking_cost)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=2))

        # Two separate fill events, each costed on ITS OWN notional
        # (5 shares * 100.00 = 500.00 each), never one combined notional.
        assert calls == [Decimal("500.00"), Decimal("500.00")]

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        # 1,000,000 - 500 - 1(cost) - 500 - 1(cost) = 998998
        funds = broker.get_funds()
        assert funds.available_balance == Decimal("998998.00")

    def test_no_duplicate_fill_on_repeated_same_price_observation_after_completion(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=2))
        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        assert report.filled_quantity == Decimal("10.00")

        # Order is now terminal (FILLED) - further record_price() calls
        # must not touch it at all (record_price()'s own loop filters to
        # PENDING/PARTIALLY_FILLED only).
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=3))
        report2 = broker.get_order_status(order.order_id)
        assert report2.filled_quantity == Decimal("10.00")
        assert report2.status is OrderStatus.FILLED

    def test_cannot_exceed_requested_quantity_across_uneven_ratio(self) -> None:
        # ratio 0.3 on qty 10: first fill round(10*0.3)=3, remaining 7;
        # F1's completion path fills the FULL remainder (7) on the next
        # observation - never a third partial slice, never overfill.
        broker = _broker(partial_fill_ratio=Decimal("0.3"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        first = broker.get_order_status(order.order_id)
        assert first.status is OrderStatus.PARTIALLY_FILLED
        assert first.filled_quantity == Decimal("3")

        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=2))
        second = broker.get_order_status(order.order_id)
        assert second.status is OrderStatus.FILLED
        assert second.filled_quantity == Decimal("10")
        assert second.filled_quantity <= order.quantity

    def test_partial_fill_ratio_one_remains_full_fill_behavior(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        assert report.filled_quantity == Decimal("10")

        # A further price observation must be a no-op - order already
        # terminal, F1's completion branch never fires for a FILLED order.
        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=2))
        report2 = broker.get_order_status(order.order_id)
        assert report2.filled_quantity == Decimal("10")
        assert report2.average_fill_price == Decimal("100.00")


# ============================================================
# F2 — LIMIT order + slippage boundary
# ============================================================


class TestF2LimitOrderSlippageBoundary:
    """Section 10/20 G-J of the 64.40 directive: BUY LIMIT and SELL
    LIMIT fills must never be worse than the stated limit price, even
    under nonzero slippage; zero slippage is unchanged; a LIMIT order
    that never crosses never fills."""

    def test_buy_limit_clamped_to_limit_price_under_adverse_slippage(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(side=Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        # Unclamped would be 100.00 * 1.01 = 101.00 (worse for a BUY).
        assert report.average_fill_price == Decimal("100.00")
        assert report.average_fill_price <= order.limit_price  # type: ignore[operator]

    def test_sell_limit_clamped_to_limit_price_under_adverse_slippage(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(side=Side.SELL, order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        # Unclamped would be 100.00 * 0.99 = 99.00 (worse for a SELL).
        assert report.average_fill_price == Decimal("100.00")
        assert report.average_fill_price >= order.limit_price  # type: ignore[operator]

    def test_zero_slippage_limit_fill_unchanged(self) -> None:
        broker = _broker(slippage_percent=Decimal("0"))
        order = _order(side=Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        assert report.average_fill_price == Decimal("100.00")

    def test_limit_not_crossed_does_not_fill(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(side=Side.BUY, order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
        broker.submit_order(order)
        # Price stays above the BUY limit - never crosses.
        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=1))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.PENDING
        assert report.filled_quantity == Decimal("0")

    def test_stop_loss_limit_leg_also_clamped_to_its_limit_price(self) -> None:
        # STOP_LOSS's own limit_price is the same kind of stated
        # boundary as plain LIMIT - the F2 fix applies there too.
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(
            side=Side.SELL,
            order_type=OrderType.STOP_LOSS,
            trigger_price=Decimal("95.00"),
            limit_price=Decimal("94.00"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("94.50"), BASE + timedelta(seconds=1))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        # Unclamped would be 94.00 * 0.99 = 93.06 (worse for a SELL).
        assert report.average_fill_price == Decimal("94.00")
        assert report.average_fill_price >= order.limit_price  # type: ignore[operator]


# ============================================================
# Transaction cost / accounting compatibility around F1 and F2
# ============================================================


class TestF1F2AccountingCompatibility:
    """Section 11/20 M-P of the 64.40 directive: transaction cost is
    always based on the ACTUAL final (post-clamp) fill price, never the
    raw observed price or the pre-slippage price; realized_net_pnl and
    unrealized_pnl remain correct through an F1 multi-fill sequence and
    an F2 clamped fill."""

    def test_transaction_cost_based_on_final_clamped_fill_price_not_raw_price(self) -> None:
        seen_notional: list[Decimal] = []

        def _cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
            seen_notional.append(notional)
            return Decimal("0")

        broker = _broker(slippage_percent=Decimal("1"), compute_cost=_cost)
        order = _order(
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100.00"),
            quantity=Decimal("10"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        # notional must be based on the CLAMPED 100.00, not the
        # unclamped 101.00 slipped price.
        assert seen_notional == [Decimal("1000.00")]

    def test_realized_net_pnl_correct_after_f1_multi_fill_round_trip(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        entry = _order(
            order_id="entry-1",
            idempotency_key="idem-entry-1",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        broker.submit_order(entry)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=2))
        entry_report = broker.get_order_status(entry.order_id)
        assert entry_report.status is OrderStatus.FILLED
        assert entry_report.filled_quantity == Decimal("10.00")

        # Close the full position at 110.00 with a full-ratio SELL MARKET.
        broker2 = broker  # same broker, still partial_fill_ratio=0.5
        exit_order = _order(
            order_id="exit-1",
            idempotency_key="idem-exit-1",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        broker2.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=3))
        broker2.submit_order(exit_order)
        # The exit itself is subject to the same 0.5 ratio -> partially
        # filled first, then completed by F1's completion path.
        broker2.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=4))

        exit_report = broker2.get_order_status(exit_order.order_id)
        assert exit_report.status is OrderStatus.FILLED
        assert exit_report.filled_quantity == Decimal("10.00")

        trades = broker2.get_trades()
        total_realized_net_pnl = sum(
            (t.realized_net_pnl or Decimal("0") for t in trades), Decimal("0")
        )
        # Two Trade records (5 shares closed each, F1's two-step exit
        # completion): (110 - 100) * 5 + (110 - 100) * 5 = 100.00 gross,
        # zero cost (compute_cost=_no_cost) -> realized_net_pnl == gross.
        assert len(trades) == 2
        assert total_realized_net_pnl == Decimal("100.00")

        positions = broker2.get_positions()
        assert len(positions) == 1
        from intraday.domain.position.contracts import PositionStatus

        assert positions[0].status is PositionStatus.CLOSED

    def test_unrealized_pnl_correct_after_f2_clamped_entry_fill(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100.00"),
            quantity=Decimal("10"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))
        # Entry filled (clamped) at exactly 100.00 -> mark at 100.00 ->
        # unrealized_pnl must be exactly zero, never off by the
        # would-have-been-101.00 slipped price.
        positions = broker.get_positions()
        assert positions[0].unrealized_pnl == Decimal("0")

        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=2))
        positions2 = broker.get_positions()
        assert positions2[0].unrealized_pnl == Decimal("50.00")  # (105-100)*10


# ============================================================
# Shared slippage function
# ============================================================


class TestSharedSlippageFunction:
    """Section 12-14/20 K-L of the 64.40 directive: ONE pure function,
    called by both Backtest's `CostModel` implementations and Paper's
    `PaperBroker._attempt_fill`, proven by monkeypatching the shared
    function itself and observing both callers use the patched result -
    not merely asserting the two formulas happen to produce the same
    number (which structurally-duplicated code could also do)."""

    def test_flat_percentage_formula_buy(self) -> None:
        result = apply_flat_percentage_slippage(
            is_buy=True, price=Decimal("100.00"), slippage_percent=Decimal("1")
        )
        assert result == Decimal("101.00")

    def test_flat_percentage_formula_sell(self) -> None:
        result = apply_flat_percentage_slippage(
            is_buy=False, price=Decimal("100.00"), slippage_percent=Decimal("1")
        )
        assert result == Decimal("99.00")

    def test_zero_slippage_is_identity(self) -> None:
        assert apply_flat_percentage_slippage(
            is_buy=True, price=Decimal("250.00"), slippage_percent=Decimal("0")
        ) == Decimal("250.00")
        assert apply_flat_percentage_slippage(
            is_buy=False, price=Decimal("250.00"), slippage_percent=Decimal("0")
        ) == Decimal("250.00")

    def test_negative_slippage_percent_rejected(self) -> None:
        with pytest.raises(ValueError):
            apply_flat_percentage_slippage(
                is_buy=True, price=Decimal("100.00"), slippage_percent=Decimal("-1")
            )

    def test_backtest_flat_percentage_cost_model_calls_shared_function(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, object]] = []
        real = apply_flat_percentage_slippage

        def _spy(**kwargs: object) -> Decimal:
            calls.append(kwargs)
            return real(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "intraday.research.backtesting.cost_model.apply_flat_percentage_slippage", _spy
        )
        model = FlatPercentageCostModel(
            brokerage_percent=Decimal("0"), slippage_percent=Decimal("2")
        )
        result = model.slippage_adjusted_price(
            StrategyDirection.BULLISH, Decimal("100.00"), entering=True
        )
        assert len(calls) == 1
        assert calls[0] == {
            "is_buy": True,
            "price": Decimal("100.00"),
            "slippage_percent": Decimal("2"),
        }
        assert result == Decimal("102.00")

    def test_backtest_indian_cost_model_calls_shared_function(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, object]] = []
        real = apply_flat_percentage_slippage

        def _spy(**kwargs: object) -> Decimal:
            calls.append(kwargs)
            return real(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "intraday.research.backtesting.cost_model.apply_flat_percentage_slippage", _spy
        )
        model: IndianCashEquityIntradayCostModel = verified_nse_cash_equity_intraday_cost_model(
            slippage_percent=Decimal("0.5")
        )
        model.slippage_adjusted_price(StrategyDirection.BEARISH, Decimal("200.00"), entering=True)
        assert len(calls) == 1
        # BEARISH entering -> a short entry -> a SELL leg.
        assert calls[0]["is_buy"] is False

    def test_paper_broker_calls_shared_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, object]] = []
        real = apply_flat_percentage_slippage

        def _spy(**kwargs: object) -> Decimal:
            calls.append(kwargs)
            return real(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "intraday.infrastructure.brokers.paper.broker.apply_flat_percentage_slippage", _spy
        )
        broker = _broker(slippage_percent=Decimal("1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, side=Side.BUY, quantity=Decimal("10"))
        broker.submit_order(order)

        assert len(calls) == 1
        assert calls[0] == {
            "is_buy": True,
            "price": Decimal("100.00"),
            "slippage_percent": Decimal("1"),
        }

    def test_backtest_and_paper_produce_identical_numbers_for_same_inputs(self) -> None:
        model = FlatPercentageCostModel(
            brokerage_percent=Decimal("0"), slippage_percent=Decimal("1.5")
        )
        backtest_result = model.slippage_adjusted_price(
            StrategyDirection.BULLISH, Decimal("321.00"), entering=True
        )

        cost_calls: list[Decimal] = []

        def _cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
            cost_calls.append(notional)
            return Decimal("0")

        broker = _broker(slippage_percent=Decimal("1.5"), compute_cost=_cost)
        broker.record_price(RELIANCE, Decimal("321.00"), BASE)
        order = _order(order_type=OrderType.MARKET, side=Side.BUY, quantity=Decimal("1"))
        broker.submit_order(order)
        paper_report = broker.get_order_status(order.order_id)

        # Both round to 2dp for comparison (Paper always does; Backtest's
        # own raw result is unrounded by design - see slippage.py docstring).
        assert paper_report.average_fill_price == backtest_result.quantize(Decimal("0.01"))


# ============================================================
# Risk Gate / no new abstractions
# ============================================================


class TestNoNewAbstractionsIntroduced:
    """Section 15/16, 20 Q-S of the 64.40 directive: this checkpoint
    introduces no Fill/FillEvent/ExecutionReport class and no
    partial-exit engine."""

    def test_no_fill_class_exists_in_broker_module(self) -> None:
        # Checkpoint 64.42 note: this assertion originally proved 64.40
        # introduced no Fill producer wiring — correct AT THE TIME. 64.42
        # is the checkpoint explicitly directed to wire the canonical
        # `intraday.domain.execution.contracts.Fill` into `PaperBroker`
        # as an IMPORT (`from ... import Fill, FillSource`), so
        # `hasattr(broker_module, "Fill")` is now expected True — the
        # module-level name is the imported canonical contract, not a
        # locally-defined new Fill/FillEvent/ExecutionReport class. The
        # part of this test that still matters — no NEW class named
        # FillEvent/ExecutionReport is defined — remains asserted below.
        import intraday.infrastructure.brokers.paper.broker as broker_module
        from intraday.domain.execution.contracts import Fill as CanonicalFill

        assert broker_module.Fill is CanonicalFill
        assert not hasattr(broker_module, "FillEvent")
        assert not hasattr(broker_module, "ExecutionReport")

    def test_no_partial_exit_engine_module_created(self) -> None:
        import importlib

        for bad_name in (
            "intraday.domain.execution.partial_exit_engine",
            "intraday.research.backtesting.partial_exit",
        ):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(bad_name)
