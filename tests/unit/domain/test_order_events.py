# tests/unit/domain/test_order_events.py
#
# Checkpoint 34 Part 5/18: OrderEvent contract invariants.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.order.contracts import OrderStatus
from intraday.domain.order.events import OrderEvent, OrderEventType

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _event(**overrides: object) -> OrderEvent:
    fields: dict[str, object] = {
        "event_id": "evt-1",
        "event_type": OrderEventType.ORDER_FILLED,
        "order_id": "ord-1",
        "correlation_id": "corr-1",
        "timestamp_utc": NOW,
        "received_at_utc": NOW,
        "previous_state": OrderStatus.PENDING,
        "new_state": OrderStatus.FILLED,
        "quantity": Decimal("10"),
        "filled_quantity": Decimal("10"),
        "remaining_quantity": Decimal("0"),
    }
    fields.update(overrides)
    return OrderEvent(**fields)  # type: ignore[arg-type]


def test_valid_event_constructs() -> None:
    event = _event()
    assert event.new_state is OrderStatus.FILLED


def test_filled_plus_remaining_must_equal_quantity() -> None:
    with pytest.raises(ValueError, match="filled_quantity"):
        _event(
            filled_quantity=Decimal("5"), remaining_quantity=Decimal("2"), quantity=Decimal("10")
        )


def test_event_id_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="event_id"):
        _event(event_id="  ")


def test_correlation_id_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="correlation_id"):
        _event(correlation_id="")


def test_negative_filled_quantity_rejected() -> None:
    with pytest.raises(ValueError, match="filled_quantity"):
        _event(
            filled_quantity=Decimal("-1"), remaining_quantity=Decimal("11"), quantity=Decimal("10")
        )


def test_received_at_before_timestamp_rejected() -> None:
    earlier = NOW.replace(minute=19)
    with pytest.raises(ValueError, match="received_at_utc"):
        _event(timestamp_utc=NOW, received_at_utc=earlier)


def test_price_must_be_positive_when_provided() -> None:
    with pytest.raises(ValueError, match="price"):
        _event(price=Decimal("-5"))


def test_broker_metadata_defaults_to_empty_mapping() -> None:
    event = _event()
    assert dict(event.broker_metadata) == {}


def test_broker_metadata_never_required_for_a_valid_event() -> None:
    """No broker-specific field is required to construct a valid event -
    proves the domain layer never depends on any one broker's shape."""
    event = _event(broker_order_id=None, sequence=None)
    assert event.broker_order_id is None
    assert event.sequence is None


def test_partial_fill_event_shape() -> None:
    event = _event(
        event_type=OrderEventType.ORDER_PARTIALLY_FILLED,
        new_state=OrderStatus.PARTIALLY_FILLED,
        quantity=Decimal("10"),
        filled_quantity=Decimal("4"),
        remaining_quantity=Decimal("6"),
    )
    assert event.filled_quantity + event.remaining_quantity == event.quantity
