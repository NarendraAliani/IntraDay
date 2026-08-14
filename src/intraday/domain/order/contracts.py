# File: src/intraday/domain/order/contracts.py
#
# Canonical Order contract (Checkpoint 5) — a risk-approved EXECUTION
# REQUEST (Checkpoint 2 §5), distinct from Signal (a candidate) and from
# any broker-specific order representation. This is "Order Intent": the
# domain.order shape trading_engine/order_management works with —
# broker-specific order types/enums never leak into this contract
# (Checkpoint 3 §7: no Dhan-specific enums in the domain).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    Side,
    SignalId,
    StrategyId,
    ensure_utc,
)


class OrderType(enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"
    STOP_LOSS_MARKET = "SL-M"


class TimeInForce(enum.Enum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(enum.Enum):
    """Broker-neutral order lifecycle (extended Checkpoint 34 Part 4).
    Mapping a specific broker's status codes onto this enum is an
    `infrastructure/brokers` adapter concern (Checkpoint 3 §7), never
    represented here.

    Checkpoint 34's own research (`docs/research/EXECUTION_RESEARCH.md`,
    Checkpoint 33's `dhanhq.co/docs/v2/orders/` fetch) found Dhan's real
    order lifecycle is 7 states: TRANSIT, PENDING, REJECTED, CANCELLED,
    PART_TRADED, TRADED, EXPIRED. Checkpoint 34 Part 4 explicitly
    forbids copying broker terminology into the domain verbatim - this
    enum is deliberately BROADER than Dhan's own set (adding CREATED,
    ACKNOWLEDGED, CANCEL_REQUESTED, ERROR) because a broker-neutral
    model must represent states that are meaningful regardless of which
    broker is behind `domain.broker.BrokerGateway` - e.g. `CREATED`
    (an `OrderIntent` exists locally but has not yet been submitted to
    any broker) has no Dhan equivalent because Dhan only ever sees an
    order once it has already been submitted.

    See `domain/order/state_machine.py` for the allowed-transition
    table - this enum only defines the vocabulary, never transition
    rules (mirrors `BarStatus`/`AggregatedBar`'s own separation of
    "what states exist" from "what aggregation does with them").
    """

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    TRANSIT = "TRANSIT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A risk-approved execution request, prior to (and independent of)
    any specific broker's wire format.

    Always traceable back to the `strategy_id` that produced it.
    `signal_id` is optional because an order intent may exist without an
    originating signal (e.g. a manual/system-triggered square-off) — but
    `strategy_id` is always required, since even a square-off is executed
    under some strategy's/session's authority. `idempotency_key` is
    mandatory: it is the mechanism that prevents duplicate submission on
    retry (Checkpoint 3 §5, Redis distributed-lock role — enforced at the
    infrastructure layer in a later checkpoint, but the *field* that makes
    that possible belongs on the domain contract itself).
    """

    order_id: OrderId
    instrument_id: InstrumentId
    side: Side
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    strategy_id: StrategyId
    created_at: datetime
    idempotency_key: str
    status: OrderStatus = OrderStatus.CREATED
    signal_id: SignalId | None = None
    limit_price: Decimal | None = None
    trigger_price: Decimal | None = None

    def __post_init__(self) -> None:
        ensure_utc(self.created_at, field_name="OrderIntent.created_at")
        if self.quantity <= 0:
            raise ValueError("OrderIntent.quantity must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("OrderIntent.limit_price is required for LIMIT orders")
        if (
            self.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET)
            and self.trigger_price is None
        ):
            raise ValueError("OrderIntent.trigger_price is required for stop-loss orders")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("OrderIntent.limit_price must be positive when provided")
        if self.trigger_price is not None and self.trigger_price <= 0:
            raise ValueError("OrderIntent.trigger_price must be positive when provided")
        if not self.idempotency_key.strip():
            raise ValueError(
                "OrderIntent.idempotency_key must be non-empty (prevents duplicate submission)"
            )
