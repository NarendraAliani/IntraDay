# tests/unit/domain/test_position.py
#
# Unit tests for the Position contract (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _position(**overrides: object) -> Position:
    fields: dict[str, object] = {
        "position_id": "pos-1",
        "instrument_id": RELIANCE,
        "direction": Side.BUY,
        "quantity": Decimal("10"),
        "average_entry_price": Decimal("100"),
        "realized_pnl": Decimal("0"),
        "unrealized_pnl": Decimal("50"),
        "opened_at": NOW,
        "status": PositionStatus.OPEN,
    }
    fields.update(overrides)
    return Position(**fields)  # type: ignore[arg-type]


def test_open_position_must_not_have_closed_at() -> None:
    with pytest.raises(ValueError):
        _position(closed_at=NOW)


def test_closed_position_requires_closed_at() -> None:
    with pytest.raises(ValueError):
        _position(status=PositionStatus.CLOSED)


def test_closed_at_must_not_precede_opened_at() -> None:
    earlier = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        _position(status=PositionStatus.CLOSED, closed_at=earlier)


def test_valid_closed_position_constructs() -> None:
    later = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    position = _position(status=PositionStatus.CLOSED, closed_at=later)
    assert position.status is PositionStatus.CLOSED
