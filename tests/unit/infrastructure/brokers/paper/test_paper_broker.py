# tests/unit/infrastructure/brokers/paper/test_paper_broker.py
#
# Checkpoint 34 Part 8/9/18: exhaustive coverage of PaperBroker - all
# order types, fills, partial fills, cancellation, rejection,
# expiration, idempotency, and position/trade bookkeeping.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.broker.contracts import BrokerConnectionState
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.order.idempotency import DuplicateOrderSubmissionError
from intraday.domain.position.contracts import PositionStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker, UnknownOrderError

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
        "initial_capital": Decimal("100000"),
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
        "strategy_id": "orb-v1",
        "created_at": BASE,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def test_connection_state_is_always_authenticated() -> None:
    assert _broker().connection_state is BrokerConnectionState.AUTHENTICATED


# --- Market orders -----------------------------------------------------


def test_market_order_with_no_recorded_price_is_rejected() -> None:
    broker = _broker()
    report = broker.submit_order(_order())
    assert report.status is OrderStatus.REJECTED


def test_market_order_fills_at_latest_recorded_price() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    report = broker.submit_order(_order())
    assert report.status is OrderStatus.FILLED
    assert report.average_fill_price == Decimal("100.00")
    assert report.filled_quantity == Decimal("10")


def test_market_buy_reduces_available_balance() -> None:
    broker = _broker(initial_capital=Decimal("100000"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    funds = broker.get_funds()
    assert funds.available_balance == Decimal("99000")


def test_market_order_creates_open_position() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].status is PositionStatus.OPEN
    assert positions[0].quantity == Decimal("10")


def test_opposite_side_order_closes_position_and_records_trade() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1", side=Side.BUY))
    broker.record_price(RELIANCE, Decimal("110"), BASE)
    broker.submit_order(
        _order(order_id="ord-2", idempotency_key="idem-2", side=Side.SELL, quantity=Decimal("10"))
    )
    trades = broker.get_trades()
    assert len(trades) == 1
    assert trades[0].entry_price == Decimal("100")
    assert trades[0].exit_price == Decimal("110.00")
    assert trades[0].realized_pnl == Decimal("100.00")  # (110-100)*10
    positions = broker.get_positions()
    assert positions[0].status is PositionStatus.CLOSED


def test_insufficient_balance_rejects_order() -> None:
    broker = _broker(initial_capital=Decimal("500"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    report = broker.submit_order(_order(quantity=Decimal("10")))  # needs 1000
    assert report.status is OrderStatus.REJECTED


# --- Limit orders -----------------------------------------------------


def test_limit_buy_order_stays_pending_until_price_crosses() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("105"), BASE)
    report = broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=Decimal("100")))
    assert report.status is OrderStatus.PENDING

    broker.record_price(RELIANCE, Decimal("102"), BASE)
    assert broker.get_order_status("ord-1").status is OrderStatus.PENDING

    broker.record_price(RELIANCE, Decimal("99"), BASE)
    report = broker.get_order_status("ord-1")
    assert report.status is OrderStatus.FILLED
    assert report.average_fill_price == Decimal("100.00")  # fills at limit, not 99


def test_limit_sell_order_fills_when_price_rises_to_limit() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1", side=Side.BUY))
    report = broker.submit_order(
        _order(
            order_id="ord-2",
            idempotency_key="idem-2",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("110"),
        )
    )
    assert report.status is OrderStatus.PENDING
    broker.record_price(RELIANCE, Decimal("111"), BASE)
    assert broker.get_order_status("ord-2").status is OrderStatus.FILLED


# --- Stop-loss orders -----------------------------------------------------


def test_stop_loss_market_triggers_and_fills_at_trigger_price() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1", side=Side.BUY))
    report = broker.submit_order(
        _order(
            order_id="ord-2",
            idempotency_key="idem-2",
            side=Side.SELL,
            order_type=OrderType.STOP_LOSS_MARKET,
            trigger_price=Decimal("95"),
        )
    )
    assert report.status is OrderStatus.PENDING
    broker.record_price(RELIANCE, Decimal("94"), BASE)
    report = broker.get_order_status("ord-2")
    assert report.status is OrderStatus.FILLED
    assert report.average_fill_price == Decimal("94.00")


def test_stop_loss_limit_waits_for_fillable_price_after_trigger() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1", side=Side.BUY))
    broker.submit_order(
        _order(
            order_id="ord-2",
            idempotency_key="idem-2",
            side=Side.SELL,
            order_type=OrderType.STOP_LOSS,
            trigger_price=Decimal("95"),
            limit_price=Decimal("93"),
        )
    )
    # gaps straight down to 90: triggers (90 <= 95) but NOT fillable for a
    # sell-limit floor of 93 (90 < 93) - stays PENDING, triggered
    broker.record_price(RELIANCE, Decimal("90"), BASE)
    assert broker.get_order_status("ord-2").status is OrderStatus.PENDING
    # price recovers to the limit floor - now fillable
    broker.record_price(RELIANCE, Decimal("93"), BASE)
    assert broker.get_order_status("ord-2").status is OrderStatus.FILLED


# --- Partial fills -----------------------------------------------------


def test_partial_fill_ratio_produces_partially_filled_status() -> None:
    broker = _broker(partial_fill_ratio=Decimal("0.5"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    report = broker.submit_order(_order(quantity=Decimal("10")))
    assert report.status is OrderStatus.PARTIALLY_FILLED
    assert report.filled_quantity == Decimal("5.00")


def test_partial_fill_accumulates_across_repeated_price_updates() -> None:
    """`partial_fill_ratio` applies to the REMAINING quantity on every
    fill attempt (geometric, not linear) - documented, deliberate
    behaviour: each subsequent price update fills half of whatever is
    still outstanding, so `filled_quantity` strictly increases without
    ever silently jumping to more than what the ratio allows."""
    broker = _broker(partial_fill_ratio=Decimal("0.5"))
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=Decimal("100")))
    # LIMIT orders never fill inside submit_order itself - only a
    # subsequent record_price() call checks resting orders.
    assert broker.get_order_status("ord-1").status is OrderStatus.PENDING

    broker.record_price(RELIANCE, Decimal("100"), BASE)
    first = broker.get_order_status("ord-1")
    assert first.status is OrderStatus.PARTIALLY_FILLED
    assert first.filled_quantity == Decimal("5.00")

    broker.record_price(RELIANCE, Decimal("100"), BASE)
    second = broker.get_order_status("ord-1")
    assert second.status is OrderStatus.PARTIALLY_FILLED
    assert second.filled_quantity > first.filled_quantity


# --- Cancellation -----------------------------------------------------


def test_cancel_pending_order() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=Decimal("50")))
    report = broker.cancel_order("ord-1")
    assert report.status is OrderStatus.CANCELLED


def test_cancel_unknown_order_raises() -> None:
    broker = _broker()
    with pytest.raises(UnknownOrderError):
        broker.cancel_order("does-not-exist")


# --- Expiration -----------------------------------------------------


def test_force_expire_end_of_session_expires_pending_orders() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=Decimal("50")))
    broker.force_expire_end_of_session()
    assert broker.get_order_status("ord-1").status is OrderStatus.EXPIRED


def test_force_expire_does_not_affect_filled_orders() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order())
    broker.force_expire_end_of_session()
    assert broker.get_order_status("ord-1").status is OrderStatus.FILLED


# --- Idempotency -----------------------------------------------------


def test_duplicate_idempotency_key_raises() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1"))
    with pytest.raises(DuplicateOrderSubmissionError):
        broker.submit_order(_order(order_id="ord-2", idempotency_key="idem-1"))


# --- get_orders -----------------------------------------------------


def test_get_orders_returns_every_submitted_order() -> None:
    broker = _broker()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    broker.submit_order(_order(order_id="ord-1", idempotency_key="idem-1"))
    broker.submit_order(
        _order(
            order_id="ord-2",
            idempotency_key="idem-2",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50"),
        )
    )
    assert len(broker.get_orders()) == 2
