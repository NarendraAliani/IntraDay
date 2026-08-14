# File: src/intraday/domain/order/events.py
#
# Checkpoint 34 Part 5: canonical, broker-neutral order events. This is
# the domain-layer shape any broker adapter (paper, future Dhan)
# translates its own wire format into - `infrastructure/brokers/*`
# owns the translation, never this module. Deliberately does NOT carry
# broker-specific fields (Dhan's `OrderNo`/`ExchOrderNo`/`ReasonDescription`
# etc. stay inside the adapter that produced the event, exposed only
# via the generic `broker_metadata` mapping - Part 5's own "do not
# over-model broker-specific fields in the domain").
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from intraday.domain.order.contracts import OrderStatus
from intraday.domain.shared_kernel.contracts import OrderId, ensure_utc


class OrderEventType(enum.Enum):
    """One member per event named in Checkpoint 34 Part 5, plus nothing
    else - this is an exhaustive, closed vocabulary, not open for
    ad hoc extension by any adapter."""

    ORDER_CREATED = "ORDER_CREATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCEL_REQUESTED = "ORDER_CANCEL_REQUESTED"
    ORDER_CANCEL_ACCEPTED = "ORDER_CANCEL_ACCEPTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_MODIFIED = "ORDER_MODIFIED"
    BROKER_ERROR = "BROKER_ERROR"


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """A single, immutable fact about one order's lifecycle. Every
    field Checkpoint 34 Part 5 named is present. `broker_order_id` and
    `broker_metadata` are the ONLY places broker-specific identifiers/
    detail may appear - both are optional/generic precisely so no
    single broker's naming leaks into a required, typed field."""

    event_id: str
    event_type: OrderEventType
    order_id: OrderId
    correlation_id: str
    timestamp_utc: datetime
    """When the event genuinely occurred (broker/exchange time, or this
    process's own decision time for locally-originated events like
    ORDER_CREATED) - distinct from `received_at_utc` exactly as
    `domain/market_data`'s `source_timestamp`/`fetched_at` split
    already established for quotes (Checkpoint 23)."""
    received_at_utc: datetime
    previous_state: OrderStatus | None
    new_state: OrderStatus
    quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    broker_order_id: str | None = None
    price: Decimal | None = None
    sequence: int | None = None
    """Broker-provided ordering hint, when available - `None` when the
    broker does not document one (Checkpoint 25.1 found Dhan's own
    WebSocket documentation does not confirm a sequence-numbering
    mechanism exists at all - never fabricated here)."""
    broker_metadata: MappingProxyType[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp_utc, field_name="OrderEvent.timestamp_utc")
        ensure_utc(self.received_at_utc, field_name="OrderEvent.received_at_utc")
        if not self.event_id.strip():
            raise ValueError("OrderEvent.event_id must not be empty")
        if not self.correlation_id.strip():
            raise ValueError("OrderEvent.correlation_id must not be empty")
        if self.quantity <= 0:
            raise ValueError("OrderEvent.quantity must be positive")
        if self.filled_quantity < 0:
            raise ValueError("OrderEvent.filled_quantity must not be negative")
        if self.remaining_quantity < 0:
            raise ValueError("OrderEvent.remaining_quantity must not be negative")
        if self.filled_quantity + self.remaining_quantity != self.quantity:
            raise ValueError("OrderEvent.filled_quantity + remaining_quantity must equal quantity")
        if self.price is not None and self.price <= 0:
            raise ValueError("OrderEvent.price must be positive when provided")
        if self.received_at_utc < self.timestamp_utc:
            raise ValueError(
                "OrderEvent.received_at_utc must not be before timestamp_utc "
                "(an event cannot be received before it happened)"
            )
