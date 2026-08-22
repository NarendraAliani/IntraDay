# tests/unit/research/test_checkpoint_64_42_paper_fill_producer.py
#
# Checkpoint 64.42 — PAPERBROKER -> CANONICAL FILL PRODUCER.
#
# Proves `PaperBroker` now constructs exactly one canonical
# `intraday.domain.execution.contracts.Fill` per ACTUAL execution event
# (never per OrderIntent), additively alongside its pre-existing
# `_PaperOrder`/`Position`/`Trade` mechanics, which remain byte-for-byte
# unchanged. Deliberately does NOT touch Backtest, Dhan, or the
# frontend, and does NOT modify the `Fill`/`FillSource` contract itself.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _flat_cost(amount: Decimal) -> object:
    def _cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
        return amount

    return _cost


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
# A/L/Q/R — MARKET full fill -> exactly one Fill, FillSource.PAPER,
# correct instrument/side
# ============================================================


class TestMarketFullFill:
    def test_market_full_fill_produces_exactly_one_fill(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        fills = broker.get_fills()
        assert len(fills) == 1
        fill = fills[0]
        assert isinstance(fill, Fill)
        assert fill.quantity == Decimal("10")
        assert fill.status_at_fill is OrderStatus.FILLED
        assert fill.source is FillSource.PAPER
        assert fill.instrument_id == RELIANCE
        assert fill.side is Side.BUY


# ============================================================
# B/C/J/K/Y — MARKET partial fill (F1 completion) -> multiple Fills,
# shared order_id, distinct fill_id, correct statuses, no overfill
# ============================================================


class TestMarketPartialFillMultiFill:
    def test_partial_then_completion_produces_two_fills_summing_to_requested_quantity(
        self,
    ) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        fills = broker.get_fills()
        assert len(fills) == 1
        assert fills[0].quantity == Decimal("5")
        assert fills[0].status_at_fill is OrderStatus.PARTIALLY_FILLED

        # F1 completion: next record_price() call fills the remainder in full.
        broker.record_price(RELIANCE, Decimal("101.00"), BASE + timedelta(seconds=5))

        fills = broker.get_fills()
        assert len(fills) == 2
        fill_1, fill_2 = fills

        assert fill_1.quantity == Decimal("5")
        assert fill_1.status_at_fill is OrderStatus.PARTIALLY_FILLED
        assert fill_2.quantity == Decimal("5")
        assert fill_2.status_at_fill is OrderStatus.FILLED

        # C: shared order_id, distinct fill_id.
        assert fill_1.order_id == fill_2.order_id == order.order_id
        assert fill_1.fill_id != fill_2.fill_id

        # Sum equals the requested quantity, no overfill.
        assert fill_1.quantity + fill_2.quantity == order.quantity

        # Execution order preserved (§23) — fill_1 observed strictly
        # before fill_2, matching actual execution sequence.
        assert fill_1.timestamp < fill_2.timestamp

    def test_no_overfill_across_multiple_fills(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.3"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=5))

        total = sum((f.quantity for f in broker.get_fills()), Decimal("0"))
        assert total == order.quantity


# ============================================================
# D/S/T — Fill quantity/price exactly match what the existing
# position update already used (never independently recomputed)
# ============================================================


class TestFillMatchesPositionUpdate:
    def test_fill_quantity_and_price_equal_actual_position_update_values(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("250.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("7"))
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        position = broker.get_positions()[0]

        # The position was opened by exactly this one fill event.
        assert fill.quantity == position.quantity
        assert fill.price == position.average_entry_price

    def test_fill_price_equals_order_report_average_fill_price(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("250.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("7"))
        report = broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.price == report.average_fill_price
        assert fill.quantity == report.filled_quantity


# ============================================================
# E/F/G — LIMIT boundary (64.40 F2) correctly reflected in Fill.price;
# SELL LIMIT boundary too
# ============================================================


class TestLimitBoundaryReflectedInFill:
    def test_buy_limit_crossing_fill_price_never_worse_than_limit(self) -> None:
        # slippage_percent pushes the raw price worse than the limit;
        # F2's clamp must keep the ACTUAL fill at the limit price, and
        # the Fill must record that same clamped price, never 101.
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(
            order_type=OrderType.LIMIT,
            side=Side.BUY,
            quantity=Decimal("10"),
            limit_price=Decimal("100.00"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        fills = broker.get_fills()
        assert len(fills) == 1
        fill = fills[0]
        assert fill.price == Decimal("100.00")
        assert fill.status_at_fill is OrderStatus.FILLED

    def test_sell_limit_crossing_fill_price_never_worse_than_limit(self) -> None:
        broker = _broker(slippage_percent=Decimal("1"))
        order = _order(
            order_type=OrderType.LIMIT,
            side=Side.SELL,
            quantity=Decimal("10"),
            limit_price=Decimal("100.00"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=1))

        fills = broker.get_fills()
        assert len(fills) == 1
        fill = fills[0]
        assert fill.price == Decimal("100.00")
        assert fill.side is Side.SELL


# ============================================================
# H/I — STOP_LOSS_MARKET and STOP_LOSS Fills
# ============================================================


class TestStopOrderFills:
    def test_stop_loss_market_produces_fill_at_trigger_price(self) -> None:
        broker = _broker()
        order = _order(
            order_type=OrderType.STOP_LOSS_MARKET,
            side=Side.SELL,
            quantity=Decimal("5"),
            trigger_price=Decimal("90.00"),
        )
        broker.submit_order(order)
        assert broker.get_fills() == ()  # not yet triggered

        broker.record_price(RELIANCE, Decimal("89.50"), BASE + timedelta(seconds=1))

        fills = broker.get_fills()
        assert len(fills) == 1
        fill = fills[0]
        assert fill.price == Decimal("89.50")
        assert fill.status_at_fill is OrderStatus.FILLED
        assert fill.source is FillSource.PAPER

    def test_stop_loss_produces_fill_at_clamped_limit_leg(self) -> None:
        broker = _broker()
        order = _order(
            order_type=OrderType.STOP_LOSS,
            side=Side.SELL,
            quantity=Decimal("5"),
            trigger_price=Decimal("90.00"),
            limit_price=Decimal("88.00"),
        )
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("89.00"), BASE + timedelta(seconds=1))

        fills = broker.get_fills()
        assert len(fills) == 1
        fill = fills[0]
        assert fill.price == Decimal("88.00")


# ============================================================
# M/N — actual transaction cost and slippage captured per Fill
# ============================================================


class TestCostAndSlippageCapture:
    def test_transaction_cost_matches_compute_cost_result(self) -> None:
        broker = _broker(compute_cost=_flat_cost(Decimal("12.34")))  # type: ignore[arg-type]
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.transaction_cost == Decimal("12.34")

    def test_slippage_applied_is_signed_actual_adjustment(self) -> None:
        # BUY with 1% slippage: raw 100 -> slipped 101.00 (worse for buyer).
        broker = _broker(slippage_percent=Decimal("1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, side=Side.BUY, quantity=Decimal("10"))
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.price == Decimal("101.00")
        assert fill.slippage_applied == Decimal("1.00")

    def test_slippage_applied_negative_for_sell(self) -> None:
        # SELL with 1% slippage: raw 100 -> slipped 99.00 (worse for seller).
        broker = _broker(slippage_percent=Decimal("1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, side=Side.SELL, quantity=Decimal("10"))
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.price == Decimal("99.00")
        assert fill.slippage_applied == Decimal("-1.00")

    def test_multi_fill_order_attributes_cost_per_fill_not_per_order(self) -> None:
        # Distinct cost per fill event via a stateful compute_cost closure.
        calls: list[Decimal] = []

        def _incrementing_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
            amount = Decimal("1.00") * (len(calls) + 1)
            calls.append(amount)
            return amount

        broker = _broker(partial_fill_ratio=Decimal("0.5"), compute_cost=_incrementing_cost)  # type: ignore[arg-type]
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=5))

        fills = broker.get_fills()
        assert len(fills) == 2
        assert fills[0].transaction_cost == Decimal("1.00")
        assert fills[1].transaction_cost == Decimal("2.00")


# ============================================================
# O — Fill timestamp is actual execution time, UTC-aware, never
# OrderIntent.created_at
# ============================================================


class TestFillTimestamp:
    def test_fill_timestamp_is_utc_aware_and_not_order_created_at(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"), created_at=BASE)
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.timestamp.tzinfo is not None
        assert fill.timestamp != order.created_at


# ============================================================
# P — Fill.order_id equals OrderIntent.order_id
# ============================================================


class TestFillOrderIdIdentity:
    def test_fill_order_id_equals_intent_order_id(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_id="ord-xyz-999", order_type=OrderType.MARKET, quantity=Decimal("3"))
        broker.submit_order(order)

        fill = broker.get_fills()[0]
        assert fill.order_id == order.order_id == "ord-xyz-999"


# ============================================================
# U/V/W — realized_net_pnl / unrealized_pnl / equity unchanged by
# Fill's mere presence
# ============================================================


class TestAccountingUnchanged:
    def test_realized_net_pnl_unrealized_pnl_equity_unaffected_by_fill_producer(self) -> None:
        broker = _broker(compute_cost=_flat_cost(Decimal("2.00")))  # type: ignore[arg-type]
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        buy = _order(
            order_id="ord-buy",
            idempotency_key="idem-buy",
            order_type=OrderType.MARKET,
            side=Side.BUY,
            quantity=Decimal("10"),
        )
        broker.submit_order(buy)

        broker.record_price(RELIANCE, Decimal("110.00"), BASE + timedelta(seconds=5))
        sell = _order(
            order_id="ord-sell",
            idempotency_key="idem-sell",
            order_type=OrderType.MARKET,
            side=Side.SELL,
            quantity=Decimal("10"),
        )
        broker.submit_order(sell)

        trades = broker.get_trades()
        assert len(trades) == 1
        trade = trades[0]

        # Independently-known-correct values for this scenario: gross
        # realized = (110-100)*10 = 100; two Decimal("2.00") costs
        # attributed = 4.00 total; net = 96.00.
        assert trade.realized_pnl == Decimal("100.00")
        assert trade.realized_net_pnl == Decimal("96.00")
        assert broker.get_total_unrealized_pnl() == Decimal("0")
        assert broker.get_equity() == Decimal("1000000") + Decimal("96.00")

        # Two Fill events were produced (BUY, SELL) but they did not
        # change any of the above — they are purely additive.
        assert len(broker.get_fills()) == 2


# ============================================================
# X/Z — no duplicate Fill after terminal state; no Fill for a
# rejected order
# ============================================================


class TestNoFillOnRejectionOrAfterTerminal:
    def test_no_fill_for_rejected_market_order_no_reference_price(self) -> None:
        broker = _broker()
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        report = broker.submit_order(order)

        assert report.status is OrderStatus.REJECTED
        assert broker.get_fills() == ()

    def test_no_fill_for_rejected_market_order_insufficient_funds(self) -> None:
        broker = _broker(initial_capital=Decimal("10"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        report = broker.submit_order(order)

        assert report.status is OrderStatus.REJECTED
        assert broker.get_fills() == ()

    def test_no_duplicate_fill_after_order_reaches_terminal_filled_state(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)
        assert len(broker.get_fills()) == 1

        # Further, unrelated price ticks on the same instrument must not
        # spawn additional Fills for an already-FILLED order.
        broker.record_price(RELIANCE, Decimal("105.00"), BASE + timedelta(seconds=5))
        broker.record_price(RELIANCE, Decimal("95.00"), BASE + timedelta(seconds=10))
        assert len(broker.get_fills()) == 1


# ============================================================
# AA/AB/AC/AD — no Fill contract changes, no Backtest/Dhan/frontend
# touched (mechanical/documentary checks)
# ============================================================


class TestScopeDiscipline:
    def test_fill_contract_fields_unchanged_from_64_41(self) -> None:
        expected_fields = {
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
        assert set(Fill.__dataclass_fields__.keys()) == expected_fields

    def test_no_fillbook_fillmanager_executionledger_introduced(self) -> None:
        import intraday.infrastructure.brokers.paper.broker as broker_module

        for forbidden in ("FillBook", "FillManager", "ExecutionLedger", "EventStore"):
            assert not hasattr(broker_module, forbidden)


# ============================================================
# §24 — fill_id uniqueness across 100+ generated fills
# ============================================================


class TestFillIdUniqueness:
    def test_fill_ids_unique_across_many_fills(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.1"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("100"))
        broker.submit_order(order)

        # Complete the remainder across many ticks to accumulate fills,
        # then generate more fills across other instruments/orders too.
        t = BASE
        for _i in range(20):
            t = t + timedelta(seconds=1)
            broker.record_price(RELIANCE, Decimal("100.00"), t)
            broker.record_price(TCS, Decimal("50.00"), t)

        for i in range(100):
            t = t + timedelta(seconds=1)
            broker.record_price(TCS, Decimal("50.00"), t)
            o = _order(
                order_id=f"ord-many-{i}",
                idempotency_key=f"idem-many-{i}",
                instrument_id=TCS,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
            )
            broker.submit_order(o)

        fills = broker.get_fills()
        assert len(fills) >= 100
        fill_ids = [f.fill_id for f in fills]
        assert len(fill_ids) == len(set(fill_ids))


# ============================================================
# §25 — Fill construction remains O(1) per event / cheap in bulk
# ============================================================


class TestFillProducerPerformance:
    def test_two_thousand_fills_construct_quickly(self) -> None:
        import time

        broker = _broker()
        broker.record_price(TCS, Decimal("50.00"), BASE)

        start = time.perf_counter()
        t = BASE
        for i in range(2000):
            t = t + timedelta(seconds=1)
            o = _order(
                order_id=f"ord-perf-{i}",
                idempotency_key=f"idem-perf-{i}",
                instrument_id=TCS,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
            )
            broker.submit_order(o)
        elapsed = time.perf_counter() - start

        assert len(broker.get_fills()) == 2000
        # Generous smoke-test threshold (not a tight microbenchmark),
        # matching 64.41's own performance-test discipline.
        assert elapsed < 10.0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
