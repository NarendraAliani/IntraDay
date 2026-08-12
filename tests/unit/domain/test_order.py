# tests/unit/domain/test_order.py
#
# Unit tests for the OrderIntent contract (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "orb-v1",
        "created_at": NOW,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def test_market_order_needs_no_limit_price() -> None:
    order = _order()
    assert order.limit_price is None


def test_limit_order_requires_limit_price() -> None:
    with pytest.raises(ValueError):
        _order(order_type=OrderType.LIMIT)


def test_stop_loss_order_requires_trigger_price() -> None:
    with pytest.raises(ValueError):
        _order(order_type=OrderType.STOP_LOSS)


def test_idempotency_key_is_mandatory() -> None:
    with pytest.raises(ValueError):
        _order(idempotency_key="  ")


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _order(quantity=Decimal("0"))
