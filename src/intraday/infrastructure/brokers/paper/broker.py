# File: src/intraday/infrastructure/brokers/paper/broker.py
#
# Checkpoint 34 Part 7-9: PaperBroker - a genuine, event-driven
# simulated broker implementing `domain.broker.BrokerGateway` exactly,
# NOT a special-cased shortcut. `PaperBroker` and a future `DhanBroker`
# both consume the same canonical `OrderIntent` and expose the same
# Protocol surface:
#
#                 BrokerGateway
#                    /      \
#               PaperBroker   DhanBroker (future)
#
# Deliberately Django-free and in-memory (mirrors every other
# `infrastructure/brokers`/`infrastructure/market_data_providers`
# client in this project - plain Python, no framework dependency) -
# the CALLER (Checkpoint 34 Part 8's paper-trading application service)
# is responsible for persisting whatever this broker reports into the
# durable ledger (`PaperOrderRecord`/`PaperTradeRecord`/
# `PaperPositionRecord`/`PaperFundsRecord`, Part 12) - exactly how a
# real Dhan adapter's reported state would need to be persisted
# locally too. This keeps `PaperBroker` itself trivially unit-testable
# without a database, matching every other pure-logic module in this
# project (`domain/market_data/aggregation.py`,
# `research/backtesting/engine.py`).
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from intraday.domain.broker.contracts import (
    BrokerConnectionState,
    BrokerOrderStatusReport,
    Funds,
)
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType
from intraday.domain.order.events import OrderEvent, OrderEventType
from intraday.domain.order.idempotency import (
    DuplicateOrderSubmissionError,
    derive_correlation_id,
)
from intraday.domain.order.state_machine import validate_transition
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    PositionId,
    Side,
    TradeId,
)
from intraday.domain.trade.contracts import Trade


class UnknownOrderError(KeyError):
    """Raised by `get_order_status()`/`cancel_order()`/`modify_order()`
    for an `order_id` this `PaperBroker` instance has never seen."""


class NoReferencePriceError(RuntimeError):
    """Raised when a MARKET order is submitted for an instrument this
    `PaperBroker` has never received a price for via `record_price()` -
    never fabricates a price, mirrors this project's "reject, never
    guess" discipline (`domain/market_data/quality.py`)."""


@dataclass
class _PaperOrder:
    """Internal, mutable order-tracking record - never exposed
    directly; every external observation goes through
    `BrokerOrderStatusReport`/`OrderEvent`."""

    intent: OrderIntent
    correlation_id: str
    status: OrderStatus
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    events: list[OrderEvent] = field(default_factory=list)


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PaperBroker:
    """Structurally implements `domain.broker.contracts.BrokerGateway`.

    Execution model (Part 9, documented explicitly, never silently
    invented):
      - MARKET orders fill immediately against the LATEST price
        `record_price()` has observed for the instrument - analogous to
        the backtest engine's "next available price" rule
        (`research/backtesting/engine.py`'s next-bar-open fill), never
        the price at the moment the strategy DECIDED to trade (which
        would be look-ahead).
      - LIMIT orders remain PENDING until a subsequent `record_price()`
        call observes a price at or better than the limit price (BUY:
        price <= limit; SELL: price >= limit), then fill at the LIMIT
        price (never a better price is fabricated, and never worse -
        matches standard limit-order semantics).
      - STOP_LOSS / STOP_LOSS_MARKET orders remain PENDING until a
        subsequent `record_price()` call crosses the trigger price
        (BUY: price >= trigger; SELL: price <= trigger); once
        triggered, STOP_LOSS_MARKET fills immediately at that price,
        STOP_LOSS fills only if that same price is at least as good as
        the order's own limit_price (else it remains PENDING,
        triggered, waiting for a fillable price - standard stop-limit
        behaviour).
      - Partial fills: a configurable `partial_fill_ratio` (default
        `Decimal("1")`, i.e. always a full fill) lets a caller
        deliberately model partial fills for testing/realism without
        this broker silently always filling 100%.
      - Slippage: a configurable flat `slippage_percent` is applied to
        every fill price (BUY: price paid is worse by the slippage
        percentage; SELL: price received is worse) - the SAME kind of
        flat-percentage MODEL ASSUMPTION already established and
        disclosed for backtesting (`research.backtesting`'s own
        documented "MODEL ASSUMPTION, not verified" language) reused
        here, not reinvented.
      - Costs: an injected `compute_cost` callable
        (`(is_buy: bool, notional: Decimal) -> Decimal`) - never a
        second, competing cost formula. The caller (Checkpoint 34's
        paper-trading application service) is expected to inject the
        SAME verified `IndianCashEquityIntradayCostModel` already used
        by backtesting (Checkpoint 29), via a small adapter closure -
        this module never imports `research.backtesting.cost_model`
        directly (`.importlinter` contract 4 forbids
        `infrastructure` from being a party to that boundary at all,
        but the INJECTION pattern is reused deliberately, mirroring
        Checkpoint 26/27's own feature-computation injection).
      - End-of-data / no-price handling: a MARKET order submitted for
        an instrument with no recorded price is REJECTED
        (`NoReferencePriceError` surfaces as a REJECTED status, never
        a silently-skipped or fabricated fill).
    """

    def __init__(
        self,
        *,
        initial_capital: Decimal,
        compute_cost: Callable[[bool, Decimal], Decimal],
        slippage_percent: Decimal = Decimal("0"),
        partial_fill_ratio: Decimal = Decimal("1"),
        clock: Callable[[], datetime],
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not (Decimal("0") < partial_fill_ratio <= Decimal("1")):
            raise ValueError("partial_fill_ratio must be in (0, 1]")
        self._compute_cost = compute_cost
        self._slippage_percent = slippage_percent
        self._partial_fill_ratio = partial_fill_ratio
        self._clock = clock

        self._orders: dict[OrderId, _PaperOrder] = {}
        self._idempotency_keys: dict[str, OrderId] = {}
        self._trades: list[Trade] = []
        self._positions: dict[InstrumentId, Position] = {}
        self._latest_prices: dict[InstrumentId, Decimal] = {}
        self._available_balance = initial_capital
        self._utilized_margin = Decimal("0")

    # --- BrokerGateway Protocol surface -----------------------------------

    @property
    def connection_state(self) -> BrokerConnectionState:
        return BrokerConnectionState.AUTHENTICATED  # paper mode is always "connected"

    def submit_order(self, order: OrderIntent) -> BrokerOrderStatusReport:
        if order.idempotency_key in self._idempotency_keys:
            raise DuplicateOrderSubmissionError(
                order.idempotency_key, self._idempotency_keys[order.idempotency_key]
            )
        correlation_id = derive_correlation_id(order.idempotency_key)
        record = _PaperOrder(
            intent=order,
            correlation_id=correlation_id,
            status=OrderStatus.CREATED,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
        )
        self._orders[order.order_id] = record
        self._idempotency_keys[order.idempotency_key] = order.order_id
        self._transition(record, OrderStatus.SUBMITTED, OrderEventType.ORDER_SUBMITTED)
        self._transition(record, OrderStatus.TRANSIT, OrderEventType.ORDER_SUBMITTED)
        self._transition(record, OrderStatus.ACKNOWLEDGED, OrderEventType.ORDER_ACCEPTED)
        self._transition(record, OrderStatus.PENDING, OrderEventType.ORDER_ACCEPTED)

        if order.order_type is OrderType.MARKET:
            price = self._latest_prices.get(order.instrument_id)
            if price is None:
                self._transition(
                    record,
                    OrderStatus.REJECTED,
                    OrderEventType.ORDER_REJECTED,
                )
                return self._report(record)
            self._attempt_fill(record, price)
        # LIMIT/STOP_LOSS/STOP_LOSS_MARKET remain PENDING until a
        # matching record_price() call - never filled optimistically here.

        return self._report(record)

    def cancel_order(self, order_id: OrderId) -> BrokerOrderStatusReport:
        record = self._require(order_id)
        self._transition(
            record, OrderStatus.CANCEL_REQUESTED, OrderEventType.ORDER_CANCEL_REQUESTED
        )
        self._transition(record, OrderStatus.CANCELLED, OrderEventType.ORDER_CANCELLED)
        return self._report(record)

    def modify_order(
        self,
        order_id: OrderId,
        *,
        limit_price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        quantity: Decimal | None = None,
    ) -> BrokerOrderStatusReport:
        record = self._require(order_id)
        from dataclasses import replace

        record.intent = replace(
            record.intent,
            limit_price=limit_price if limit_price is not None else record.intent.limit_price,
            trigger_price=(
                trigger_price if trigger_price is not None else record.intent.trigger_price
            ),
            quantity=quantity if quantity is not None else record.intent.quantity,
        )
        record.events.append(
            OrderEvent(
                event_id=str(uuid.uuid4()),
                event_type=OrderEventType.ORDER_MODIFIED,
                order_id=order_id,
                correlation_id=record.correlation_id,
                timestamp_utc=self._clock(),
                received_at_utc=self._clock(),
                previous_state=record.status,
                new_state=record.status,
                quantity=record.intent.quantity,
                filled_quantity=record.filled_quantity,
                remaining_quantity=record.intent.quantity - record.filled_quantity,
            )
        )
        return self._report(record)

    def get_order_status(self, order_id: OrderId) -> BrokerOrderStatusReport:
        return self._report(self._require(order_id))

    def get_order_events(self, order_id: OrderId) -> tuple[OrderEvent, ...]:
        """Checkpoint 35 Part 3: not part of `BrokerGateway` - the full,
        ordered event history for one order, so a caller (the ledger
        persistence layer) can record every material state transition,
        not only the latest snapshot."""
        return tuple(self._require(order_id).events)

    def get_orders(self) -> tuple[BrokerOrderStatusReport, ...]:
        return tuple(self._report(record) for record in self._orders.values())

    def get_trades(self) -> tuple[Trade, ...]:
        return tuple(self._trades)

    def get_positions(self) -> tuple[Position, ...]:
        return tuple(self._positions.values())

    def get_funds(self) -> Funds:
        return Funds(
            available_balance=self._available_balance,
            utilized_margin=self._utilized_margin,
            as_of=self._clock(),
        )

    # --- Paper-specific surface (not part of BrokerGateway) --------------

    def get_latest_price(self, instrument_id: InstrumentId) -> Decimal | None:
        """Checkpoint 35 Part 4: the last price `record_price()` observed
        for `instrument_id`, or `None` if none has ever been recorded -
        used by the order-entry API to estimate notional for risk
        evaluation before a MARKET order is actually filled. Never
        fabricates a price."""
        return self._latest_prices.get(instrument_id)

    def record_price(
        self, instrument_id: InstrumentId, price: Decimal, timestamp: datetime
    ) -> None:
        """Feeds a fresh observed price - drives fills for any PENDING
        LIMIT/STOP order on this instrument. Never called by
        `submit_order()` itself; the caller (application layer,
        Checkpoint 34 Part 8) is responsible for feeding real market
        data in, exactly as a live strategy would only ever know prices
        it has actually observed."""
        if price <= 0:
            raise ValueError("price must be positive")
        self._latest_prices[instrument_id] = price
        for record in self._orders.values():
            if record.intent.instrument_id != instrument_id:
                continue
            if record.status not in (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
                continue
            self._maybe_fill_resting_order(record, price)

    def force_expire_end_of_session(self) -> None:
        """Part 9's "end-of-data handling" - every still-PENDING/
        PARTIALLY_FILLED order is explicitly EXPIRED, never silently
        dropped or left in limbo (mirrors the backtest engine's own
        end-of-series force-close discipline, Checkpoint 27)."""
        for record in self._orders.values():
            if record.status in (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
                self._transition(record, OrderStatus.EXPIRED, OrderEventType.ORDER_EXPIRED)

    # --- internal ----------------------------------------------------------

    def _require(self, order_id: OrderId) -> _PaperOrder:
        record = self._orders.get(order_id)
        if record is None:
            raise UnknownOrderError(order_id)
        return record

    def _transition(
        self, record: _PaperOrder, new_state: OrderStatus, event_type: OrderEventType
    ) -> None:
        validate_transition(record.status, new_state)
        previous = record.status
        record.status = new_state
        now = self._clock()
        record.events.append(
            OrderEvent(
                event_id=str(uuid.uuid4()),
                event_type=event_type,
                order_id=record.intent.order_id,
                correlation_id=record.correlation_id,
                timestamp_utc=now,
                received_at_utc=now,
                previous_state=previous,
                new_state=new_state,
                quantity=record.intent.quantity,
                filled_quantity=record.filled_quantity,
                remaining_quantity=record.intent.quantity - record.filled_quantity,
            )
        )

    def _maybe_fill_resting_order(self, record: _PaperOrder, price: Decimal) -> None:
        intent = record.intent
        is_buy = intent.side is Side.BUY

        if intent.order_type is OrderType.LIMIT:
            assert intent.limit_price is not None
            crosses = price <= intent.limit_price if is_buy else price >= intent.limit_price
            if crosses:
                self._attempt_fill(record, intent.limit_price)
            return

        if intent.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET):
            assert intent.trigger_price is not None
            triggered = price >= intent.trigger_price if is_buy else price <= intent.trigger_price
            if not triggered:
                return
            if intent.order_type is OrderType.STOP_LOSS_MARKET:
                self._attempt_fill(record, price)
            else:
                assert intent.limit_price is not None
                fillable = price <= intent.limit_price if is_buy else price >= intent.limit_price
                if fillable:
                    self._attempt_fill(record, intent.limit_price)
            return

    def _attempt_fill(self, record: _PaperOrder, price: Decimal) -> None:
        intent = record.intent
        is_buy = intent.side is Side.BUY
        slipped_price = _round(
            price * (Decimal("1") + self._slippage_percent / Decimal("100"))
            if is_buy
            else price * (Decimal("1") - self._slippage_percent / Decimal("100"))
        )

        remaining = intent.quantity - record.filled_quantity
        fill_quantity = _round(remaining * self._partial_fill_ratio)
        if fill_quantity <= 0 or fill_quantity > remaining:
            fill_quantity = remaining

        notional = slipped_price * fill_quantity
        cost = self._compute_cost(is_buy, notional)

        if is_buy:
            required = notional + cost
            if required > self._available_balance:
                self._transition(record, OrderStatus.REJECTED, OrderEventType.ORDER_REJECTED)
                return
            self._available_balance -= required
        else:
            self._available_balance += notional - cost

        record.filled_quantity += fill_quantity
        record.average_fill_price = slipped_price
        is_full_fill = record.filled_quantity >= intent.quantity

        target_state = OrderStatus.FILLED if is_full_fill else OrderStatus.PARTIALLY_FILLED
        event_type = (
            OrderEventType.ORDER_FILLED if is_full_fill else OrderEventType.ORDER_PARTIALLY_FILLED
        )
        self._transition(record, target_state, event_type)

        self._apply_to_position(intent, fill_quantity, slipped_price)

    def _apply_to_position(
        self, intent: OrderIntent, fill_quantity: Decimal, fill_price: Decimal
    ) -> None:
        existing = self._positions.get(intent.instrument_id)
        now = self._clock()

        if existing is None or existing.status is PositionStatus.CLOSED:
            self._positions[intent.instrument_id] = Position(
                position_id=PositionId(str(uuid.uuid4())),
                instrument_id=intent.instrument_id,
                direction=intent.side,
                quantity=fill_quantity,
                average_entry_price=fill_price,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                opened_at=now,
                status=PositionStatus.OPEN,
            )
            return

        if existing.direction == intent.side:
            total_quantity = existing.quantity + fill_quantity
            blended_price = _round(
                (existing.average_entry_price * existing.quantity + fill_price * fill_quantity)
                / total_quantity
            )
            self._positions[intent.instrument_id] = Position(
                position_id=existing.position_id,
                instrument_id=existing.instrument_id,
                direction=existing.direction,
                quantity=total_quantity,
                average_entry_price=blended_price,
                realized_pnl=existing.realized_pnl,
                unrealized_pnl=existing.unrealized_pnl,
                opened_at=existing.opened_at,
                status=PositionStatus.OPEN,
            )
            return

        # Opposite side - closes (fully or partially) the existing position.
        closing_quantity = min(existing.quantity, fill_quantity)
        direction_sign = Decimal("1") if existing.direction is Side.BUY else Decimal("-1")
        realized = direction_sign * (fill_price - existing.average_entry_price) * closing_quantity
        new_realized = existing.realized_pnl + realized

        self._trades.append(
            Trade(
                trade_id=TradeId(str(uuid.uuid4())),
                strategy_id=intent.strategy_id,
                instrument_id=intent.instrument_id,
                direction=existing.direction,
                order_ids=(intent.order_id,),
                entry_price=existing.average_entry_price,
                exit_price=fill_price,
                quantity=closing_quantity,
                realized_pnl=realized,
                opened_at=existing.opened_at,
                closed_at=now,
                position_id=existing.position_id,
            )
        )

        remaining_quantity = existing.quantity - closing_quantity
        if remaining_quantity <= 0:
            self._positions[intent.instrument_id] = Position(
                position_id=existing.position_id,
                instrument_id=existing.instrument_id,
                direction=existing.direction,
                quantity=closing_quantity,
                average_entry_price=existing.average_entry_price,
                realized_pnl=new_realized,
                unrealized_pnl=Decimal("0"),
                opened_at=existing.opened_at,
                status=PositionStatus.CLOSED,
                closed_at=now,
            )
        else:
            self._positions[intent.instrument_id] = Position(
                position_id=existing.position_id,
                instrument_id=existing.instrument_id,
                direction=existing.direction,
                quantity=remaining_quantity,
                average_entry_price=existing.average_entry_price,
                realized_pnl=new_realized,
                unrealized_pnl=existing.unrealized_pnl,
                opened_at=existing.opened_at,
                status=PositionStatus.OPEN,
            )

    def _report(self, record: _PaperOrder) -> BrokerOrderStatusReport:
        return BrokerOrderStatusReport(
            order_id=record.intent.order_id,
            instrument_id=record.intent.instrument_id,
            status=record.status,
            filled_quantity=record.filled_quantity,
            average_fill_price=record.average_fill_price,
            reported_at=self._clock(),
        )
