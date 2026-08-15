# tests/unit/control_plane/reconciliation/test_reconciler.py
#
# Checkpoint 34 Part 13/18: every divergence type, detected via
# constructed (not live) local/broker fixtures - proves detection and
# classification without needing a real second system.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.control_plane.reconciliation.contracts import DivergenceType
from intraday.control_plane.reconciliation.reconciler import (
    reconcile_funds,
    reconcile_orders,
    reconcile_positions,
    reconcile_trades,
)
from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.domain.trade.contracts import Trade

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _broker_order(order_id: str, status: OrderStatus) -> BrokerOrderStatusReport:
    return BrokerOrderStatusReport(
        order_id=order_id,
        instrument_id=RELIANCE,
        status=status,
        filled_quantity=Decimal("0"),
        average_fill_price=None,
        reported_at=NOW,
    )


def test_orders_missing_at_broker() -> None:
    divergences = reconcile_orders(local={"ord-1": OrderStatus.PENDING}, broker=(), now=NOW)
    assert len(divergences) == 1
    assert divergences[0].divergence_type is DivergenceType.MISSING_AT_BROKER


def test_orders_missing_locally() -> None:
    divergences = reconcile_orders(
        local={}, broker=(_broker_order("ord-1", OrderStatus.PENDING),), now=NOW
    )
    assert len(divergences) == 1
    assert divergences[0].divergence_type is DivergenceType.MISSING_LOCALLY


def test_orders_status_mismatch() -> None:
    divergences = reconcile_orders(
        local={"ord-1": OrderStatus.PENDING},
        broker=(_broker_order("ord-1", OrderStatus.FILLED),),
        now=NOW,
    )
    assert len(divergences) == 1
    assert divergences[0].divergence_type is DivergenceType.STATUS_MISMATCH


def test_orders_matching_status_yields_no_divergence() -> None:
    divergences = reconcile_orders(
        local={"ord-1": OrderStatus.FILLED},
        broker=(_broker_order("ord-1", OrderStatus.FILLED),),
        now=NOW,
    )
    assert divergences == ()


def test_trades_quantity_mismatch() -> None:
    local_trade = Trade(
        trade_id="t1",
        strategy_id="orb-v1",
        instrument_id=RELIANCE,
        direction=Side.BUY,
        order_ids=("ord-1",),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        quantity=Decimal("10"),
        realized_pnl=Decimal("100"),
        opened_at=NOW,
        closed_at=NOW,
    )
    broker_trade = Trade(
        trade_id="t1",
        strategy_id="orb-v1",
        instrument_id=RELIANCE,
        direction=Side.BUY,
        order_ids=("ord-1",),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        quantity=Decimal("5"),
        realized_pnl=Decimal("50"),
        opened_at=NOW,
        closed_at=NOW,
    )
    divergences = reconcile_trades(local={"t1": local_trade}, broker=(broker_trade,), now=NOW)
    types = {d.divergence_type for d in divergences}
    assert DivergenceType.QUANTITY_MISMATCH in types


def test_positions_mismatch() -> None:
    local_position = Position(
        position_id="p1",
        instrument_id=RELIANCE,
        direction=Side.BUY,
        quantity=Decimal("10"),
        average_entry_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        opened_at=NOW,
        status=PositionStatus.OPEN,
    )
    broker_position = Position(
        position_id="p1",
        instrument_id=RELIANCE,
        direction=Side.BUY,
        quantity=Decimal("5"),
        average_entry_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        opened_at=NOW,
        status=PositionStatus.OPEN,
    )
    divergences = reconcile_positions(
        local={str(RELIANCE): local_position}, broker=(broker_position,), now=NOW
    )
    assert len(divergences) == 1
    assert divergences[0].divergence_type is DivergenceType.POSITION_MISMATCH


def test_funds_mismatch() -> None:
    local_funds = Funds(available_balance=Decimal("1000"), utilized_margin=Decimal("0"), as_of=NOW)
    broker_funds = Funds(available_balance=Decimal("900"), utilized_margin=Decimal("0"), as_of=NOW)
    divergences = reconcile_funds(local=local_funds, broker=broker_funds, now=NOW)
    assert len(divergences) == 1
    assert divergences[0].divergence_type is DivergenceType.FUNDS_MISMATCH


def test_funds_matching_yields_no_divergence() -> None:
    funds = Funds(available_balance=Decimal("1000"), utilized_margin=Decimal("0"), as_of=NOW)
    divergences = reconcile_funds(local=funds, broker=funds, now=NOW)
    assert divergences == ()


def test_reconciliation_never_mutates_inputs() -> None:
    """Detect/classify/report only - no corrective action, proven by
    asserting the input collections themselves are untouched."""
    local = {"ord-1": OrderStatus.PENDING}
    broker = (_broker_order("ord-1", OrderStatus.FILLED),)
    reconcile_orders(local=local, broker=broker, now=NOW)
    assert local == {"ord-1": OrderStatus.PENDING}
    assert broker[0].status is OrderStatus.FILLED
