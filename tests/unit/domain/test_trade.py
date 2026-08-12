# tests/unit/domain/test_trade.py
#
# Unit tests for the Trade contract (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.domain.trade.contracts import Trade

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
OPENED = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)
CLOSED = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


def _trade(**overrides: object) -> Trade:
    fields: dict[str, object] = {
        "trade_id": "trd-1",
        "strategy_id": "orb-v1",
        "instrument_id": RELIANCE,
        "direction": Side.BUY,
        "order_ids": ("ord-1", "ord-2"),
        "entry_price": Decimal("100"),
        "exit_price": Decimal("104"),
        "quantity": Decimal("10"),
        "realized_pnl": Decimal("40"),
        "opened_at": OPENED,
        "closed_at": CLOSED,
    }
    fields.update(overrides)
    return Trade(**fields)  # type: ignore[arg-type]


def test_valid_trade_constructs() -> None:
    trade = _trade()
    assert trade.realized_pnl == Decimal("40")


def test_trade_requires_at_least_one_order() -> None:
    with pytest.raises(ValueError):
        _trade(order_ids=())


def test_closed_at_must_not_precede_opened_at() -> None:
    with pytest.raises(ValueError):
        _trade(closed_at=OPENED - (CLOSED - OPENED))


def test_trade_prices_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _trade(exit_price=Decimal("0"))
