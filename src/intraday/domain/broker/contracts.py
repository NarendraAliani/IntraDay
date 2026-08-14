# File: src/intraday/domain/broker/contracts.py
#
# Broker-neutral domain boundary (Checkpoint 5) — the published interface
# infrastructure/brokers/* adapters implement and
# trading_engine/broker_abstraction consumes (Rule 5.3). ZERO Dhan-specific
# concepts, ZERO HTTP/WebSocket code, ZERO credentials, ZERO network access
# exist anywhere in this file (Checkpoint 5 Sections 18, 22). This is a
# structural interface only — no method has a body, and nothing here can
# place a real order.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from intraday.domain.order.contracts import OrderIntent, OrderStatus
from intraday.domain.position.contracts import Position
from intraday.domain.shared_kernel.contracts import OrderId, ensure_utc
from intraday.domain.trade.contracts import Trade


class BrokerConnectionState(enum.Enum):
    DISCONNECTED = "DISCONNECTED"
    AUTHENTICATED = "AUTHENTICATED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class BrokerOrderStatusReport:
    """A broker's report of one order's current status, already translated
    into domain vocabulary (`OrderStatus`) by the adapter — this contract
    never carries a broker-specific status code or field."""

    order_id: OrderId
    status: OrderStatus
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    reported_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.reported_at, field_name="BrokerOrderStatusReport.reported_at")
        if self.filled_quantity < 0:
            raise ValueError("BrokerOrderStatusReport.filled_quantity must not be negative")
        if self.average_fill_price is not None and self.average_fill_price <= 0:
            raise ValueError(
                "BrokerOrderStatusReport.average_fill_price must be positive when provided"
            )


@dataclass(frozen=True, slots=True)
class Funds:
    """Checkpoint 34 Part 7/12: a deliberately SIMPLE, broker-neutral
    capital snapshot - `available_balance` and `utilized_margin` only.
    Does NOT attempt to replicate a real broker's SPAN/exposure-margin
    math (`docs/research/EXECUTION_RESEARCH.md` §2 - Dhan's own
    `POST /margincalculator` performs that calculation broker-side;
    this project has no basis, and no need this checkpoint, to
    reimplement it). A future real-broker adapter is free to populate
    this from Dhan's richer `GET /fundlimit` response - this contract
    only requires the two fields every broker-neutral capital check
    (Checkpoint 34's risk engine) actually needs."""

    available_balance: Decimal
    utilized_margin: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.as_of, field_name="Funds.as_of")
        if self.available_balance < 0:
            raise ValueError("Funds.available_balance must not be negative")
        if self.utilized_margin < 0:
            raise ValueError("Funds.utilized_margin must not be negative")


class BrokerGateway(Protocol):
    """The domain-facing broker capability contract.

    Concrete `infrastructure/brokers/<broker>` adapters (Dhan first, per
    Rule 5.3) implement this `Protocol`; `trading_engine/broker_abstraction`
    depends only on this interface, never on a concrete adapter. No method
    body exists here — this is structure only, per Checkpoint 5 Section 18
    ("only the broker-neutral domain abstraction is allowed"). Token
    lifecycle, rate limits, and broker-specific error handling are all
    adapter concerns, never represented in this Protocol's signature.
    """

    @property
    def connection_state(self) -> BrokerConnectionState: ...

    def submit_order(self, order: OrderIntent) -> BrokerOrderStatusReport: ...

    def cancel_order(self, order_id: OrderId) -> BrokerOrderStatusReport: ...

    def modify_order(
        self,
        order_id: OrderId,
        *,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
    ) -> BrokerOrderStatusReport: ...

    def get_order_status(self, order_id: OrderId) -> BrokerOrderStatusReport: ...

    def get_orders(self) -> tuple[BrokerOrderStatusReport, ...]: ...

    """Checkpoint 34 Part 7/13: every order this broker knows about
    today - the reconciliation-side counterpart to `get_order_status`
    (one order) - mirrors Dhan's own `GET /orders` (order book,
    Checkpoint 33 research)."""

    def get_trades(self) -> tuple[Trade, ...]: ...

    """Checkpoint 34 Part 7/13: every trade this broker has recorded -
    mirrors Dhan's own `GET /trades` (trade book, Checkpoint 33
    research)."""

    def get_positions(self) -> tuple[Position, ...]: ...

    def get_funds(self) -> Funds: ...

    """Checkpoint 34 Part 7/13: current capital snapshot - mirrors
    Dhan's own `GET /fundlimit` (Checkpoint 34 research), deliberately
    simplified per `Funds`'s own docstring."""
