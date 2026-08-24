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
from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType
from intraday.domain.order.events import OrderEvent, OrderEventType
from intraday.domain.order.idempotency import (
    DuplicateOrderSubmissionError,
    derive_correlation_id,
)
from intraday.domain.order.state_machine import validate_transition
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.position.mark_to_market import mark_position, position_market_value
from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    PositionId,
    Side,
    TradeId,
)
from intraday.domain.shared_kernel.slippage import apply_flat_percentage_slippage
from intraday.domain.trade.contracts import Trade
from intraday.domain.trade.net_pnl import compute_realized_net_pnl


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
        price adjusted for slippage, CLAMPED so the fill is never worse
        than the stated limit price (Checkpoint 64.40 Finding F2 fix:
        `_attempt_fill`'s `limit_boundary` parameter - BUY clamps via
        `min(slipped_price, limit_price)`, SELL via
        `max(slipped_price, limit_price)` - matches standard
        limit-order semantics even under nonzero `slippage_percent`).
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
        this broker silently always filling 100%. For a MARKET order
        left PARTIALLY_FILLED, `partial_fill_ratio` is applied ONCE, at
        initial submission - the remaining quantity then completes IN
        FULL on the next valid `record_price()` observation
        (Checkpoint 64.40 Finding F1 fix: `_maybe_fill_resting_order`'s
        `OrderType.MARKET` branch + `_attempt_fill`'s
        `force_full_remaining` parameter). LIMIT/STOP orders retain
        their pre-existing behavior: `partial_fill_ratio` applies on
        EVERY resting-order fill attempt, so a partially-filled LIMIT
        order can require several crossings to fully fill - unchanged
        by this checkpoint.
      - Slippage: a configurable flat `slippage_percent` is applied to
        every fill price via the ONE shared
        `domain.shared_kernel.slippage.apply_flat_percentage_slippage()`
        function (Checkpoint 64.40 - previously an inlined, separate
        implementation from Backtest's own
        `CostModel.slippage_adjusted_price()`, now the same call on both
        sides) (BUY: price paid is worse by the slippage percentage;
        SELL: price received is worse) - the SAME kind of
        flat-percentage MODEL ASSUMPTION already established and
        disclosed for backtesting (`research.backtesting`'s own
        documented "MODEL ASSUMPTION, not verified" language) reused
        here, not reinvented. For LIMIT/STOP_LOSS orders, the
        slippage-adjusted price is then clamped to never be worse than
        the order's own stated `limit_price` (Finding F2 fix, above).
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
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not (Decimal("0") < partial_fill_ratio <= Decimal("1")):
            raise ValueError("partial_fill_ratio must be in (0, 1]")
        self._compute_cost = compute_cost
        self._slippage_percent = slippage_percent
        self._partial_fill_ratio = partial_fill_ratio
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        """Checkpoint 64.68: ADDITIVE, fully backward compatible - every
        existing construction site omits it and keeps the previous
        `uuid.uuid4()` behaviour byte for byte. A caller that needs the
        broker's SURROGATE identifiers (event_id/fill_id/position_id/
        trade_id) to be reproducible - specifically the deterministic
        REPLAY PAPER SESSION, whose §17 acceptance criterion is "the same
        replay twice produces the same trades and positions" - injects a
        deterministic factory instead. This changes NO economic value:
        prices, quantities, costs and P&L are entirely unaffected by
        which string an identifier happens to be."""

        self._orders: dict[OrderId, _PaperOrder] = {}
        self._idempotency_keys: dict[str, OrderId] = {}
        self._trades: list[Trade] = []
        self._positions: dict[InstrumentId, Position] = {}
        self._latest_prices: dict[InstrumentId, Decimal] = {}
        self._available_balance = initial_capital
        self._utilized_margin = Decimal("0")
        # Checkpoint 64.37: ADDITIVE cost-attribution bookkeeping only —
        # accumulates the entry-side transaction cost (from the SAME
        # `compute_cost` callable already charged to `_available_balance`
        # in `_attempt_fill`) still attributable to the currently OPEN
        # quantity of each position, so `realized_net_pnl` can be computed
        # on close without ever double-charging cash (Rule 11: this is a
        # P&L ATTRIBUTION, not a second cash mutation) and without
        # changing `realized_pnl`'s existing gross formula. Never exposed
        # outside this class.
        self._position_entry_cost: dict[InstrumentId, Decimal] = {}
        # Checkpoint 64.42: ADDITIVE canonical-Fill observability only —
        # one `Fill` appended per ACTUAL execution event (never per
        # OrderIntent), in execution order, mirroring the exact same
        # in-memory-list pattern already used for `self._trades` above.
        # Never read by any existing position/order/accounting logic in
        # this class — a pure observation seam for the future producer-
        # integration checkpoint and for tests.
        self._fills: list[Fill] = []

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
                event_id=self._id_factory(),
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

    def get_fills(self) -> tuple[Fill, ...]:
        """Checkpoint 64.42: every canonical `Fill` this `PaperBroker`
        instance has actually produced, in the exact order they occurred
        (append-only list, never re-sorted). Not part of `BrokerGateway`
        (mirrors `get_order_events()` above) - additive observability
        only, never consumed by this class's own position/order/
        accounting logic, which continues to use its pre-existing
        `_PaperOrder`/`Position`/`Trade` structures exactly as before."""
        return tuple(self._fills)

    def get_positions(self) -> tuple[Position, ...]:
        return tuple(self._positions.values())

    def get_funds(self) -> Funds:
        return Funds(
            available_balance=self._available_balance,
            utilized_margin=self._utilized_margin,
            as_of=self._clock(),
        )

    # --- Paper-specific surface (not part of BrokerGateway) --------------

    def get_total_unrealized_pnl(self) -> Decimal:
        """Checkpoint 64.38: sum of `Position.unrealized_pnl` across every
        OPEN position currently tracked. Positions never yet marked via
        `record_price()` contribute `Decimal("0")` (their honest,
        unmarked value — see `mark_to_market.py` module docstring), never
        a fabricated figure. CLOSED positions never contribute (their
        `unrealized_pnl` is fixed at `Decimal("0")` at close)."""
        return sum(
            (p.unrealized_pnl for p in self._positions.values() if p.status is PositionStatus.OPEN),
            Decimal("0"),
        )

    def get_open_positions_market_value(self) -> Decimal:
        """Checkpoint 64.38: signed sum of `position_market_value()` over
        every OPEN position - a short position's market value is
        NEGATIVE (see `mark_to_market.py`'s SIGN CONVENTION), so this is
        the correct additive term for `get_equity()` below, not a naive
        absolute-value sum."""
        return sum(
            (
                position_market_value(p)
                for p in self._positions.values()
                if p.status is PositionStatus.OPEN
            ),
            Decimal("0"),
        )

    def get_equity(self) -> Decimal:
        """Checkpoint 64.38: `available_cash + market_value_of_open_positions`
        - the account's current mark-to-market equity. Deliberately a thin
        derivation over `get_funds()` and `get_open_positions_market_value()`
        rather than a third, independently-tracked running total, so this
        can never drift out of sync with either of those two authoritative
        sources."""
        return self._available_balance + self.get_open_positions_market_value()

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
        # Checkpoint 64.38: mark the position on THIS instrument (if any,
        # and if still OPEN) against the freshly observed price. Deliberately
        # placed AFTER resting-order fills above, so a fill that just closed
        # or resized this position on this same price tick is marked using
        # its post-fill state, not a stale pre-fill snapshot. `mark_position`
        # is a no-op for a CLOSED position and never touches any other
        # instrument's position (isolation preserved) or `realized_pnl`/
        # `realized_net_pnl` (read-only w.r.t. those fields).
        existing_position = self._positions.get(instrument_id)
        if existing_position is not None and existing_position.status is PositionStatus.OPEN:
            self._positions[instrument_id] = mark_position(existing_position, price)

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
                event_id=self._id_factory(),
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
                # Checkpoint 64.40 Finding F2 fix: the LIMIT price is a
                # BOUNDARY the fill must never cross past, even after
                # slippage - see `_attempt_fill`'s `limit_boundary`
                # parameter for the enforcement itself.
                self._attempt_fill(record, intent.limit_price, limit_boundary=intent.limit_price)
            return

        if intent.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET):
            assert intent.trigger_price is not None
            triggered = price >= intent.trigger_price if is_buy else price <= intent.trigger_price
            if not triggered:
                return
            if intent.order_type is OrderType.STOP_LOSS_MARKET:
                # Genuinely a MARKET fill once triggered - no stated
                # limit boundary exists for this order type, so slippage
                # is applied without any clamp, matching pre-existing
                # (already-audited, unchanged) behavior.
                self._attempt_fill(record, price)
            else:
                assert intent.limit_price is not None
                fillable = price <= intent.limit_price if is_buy else price >= intent.limit_price
                if fillable:
                    # Same F2 reasoning as plain LIMIT above: STOP_LOSS's
                    # own `limit_price` is a stated boundary the fill
                    # must never violate, even after slippage.
                    self._attempt_fill(
                        record, intent.limit_price, limit_boundary=intent.limit_price
                    )
            return

        if intent.order_type is OrderType.MARKET:
            # Checkpoint 64.40 Finding F1 fix: a MARKET order that was
            # only PARTIALLY_FILLED on its initial `submit_order()`
            # attempt (via `partial_fill_ratio < 1`) previously had NO
            # code path to complete its remaining quantity - it stayed
            # PARTIALLY_FILLED forever. The chosen intended semantics
            # (documented in the 64.40 architecture-doc append and
            # `taskReport.md`): the remaining quantity completes in FULL
            # on the next valid `record_price()` observation - the
            # liquidity constraint modeled by `partial_fill_ratio` is
            # applied once, at initial submission, not repeatedly on
            # every subsequent tick (which would otherwise geometrically
            # shrink the remainder toward, but never reaching, zero).
            if record.status is OrderStatus.PARTIALLY_FILLED:
                self._attempt_fill(record, price, force_full_remaining=True)
            return

    def _attempt_fill(
        self,
        record: _PaperOrder,
        price: Decimal,
        *,
        limit_boundary: Decimal | None = None,
        force_full_remaining: bool = False,
    ) -> None:
        """`limit_boundary`: Checkpoint 64.40 Finding F2 fix - when set
        (LIMIT and STOP_LOSS's limit leg), the post-slippage fill price
        is clamped so it can never be WORSE than the stated boundary,
        preserving this class's own documented "never worse [than
        limit]" guarantee (`__doc__` above) that slippage was previously
        able to violate. `force_full_remaining`: Checkpoint 64.40
        Finding F1 fix - when set (a MARKET order completing a prior
        partial fill on a later `record_price()` observation), the
        ENTIRE remaining quantity fills, bypassing `partial_fill_ratio`
        (which was already applied once, at initial submission)."""
        intent = record.intent
        is_buy = intent.side is Side.BUY
        slipped_price = _round(
            apply_flat_percentage_slippage(
                is_buy=is_buy, price=price, slippage_percent=self._slippage_percent
            )
        )
        if limit_boundary is not None:
            slipped_price = (
                min(slipped_price, limit_boundary) if is_buy else max(slipped_price, limit_boundary)
            )

        remaining = intent.quantity - record.filled_quantity
        if force_full_remaining:
            fill_quantity = remaining
        else:
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

        self._apply_to_position(intent, fill_quantity, slipped_price, cost)

        # Checkpoint 64.42: construct exactly ONE canonical `Fill` for
        # THIS actual execution event — additive, never a replacement for
        # the `_PaperOrder`/`Position`/`Trade` mutations above, and built
        # strictly from values this method already computed (never
        # recomputed independently, per the checkpoint directive):
        #   - `quantity`/`price` are the exact same `fill_quantity`/
        #     `slipped_price` just passed to `_apply_to_position()` above
        #     (proof: same local variables, same call).
        #   - `transaction_cost` is the exact same `cost` already charged
        #     to `_available_balance` above — this fill's own cost only,
        #     never a re-derived or order-level total.
        #   - `slippage_applied` is the actual signed adjustment this
        #     execution path applied to reach `slipped_price` starting
        #     from the reference `price` this method was invoked with
        #     (the observed market/limit/trigger price BEFORE slippage
        #     and before any F2 limit-boundary clamp) — i.e. exactly
        #     `final_price - reference_price`, matching the directive's
        #     own worked example (raw=100, slipped=99.9 ->
        #     slippage_applied=-0.1). This already reflects the F2 clamp
        #     too, since `slipped_price` is post-clamp — no separate,
        #     possibly-inconsistent recomputation is performed.
        #   - `status_at_fill` is the exact `target_state` just used for
        #     `self._transition()` above (FILLED or PARTIALLY_FILLED,
        #     never a third value).
        #   - `timestamp` is a fresh call to the SAME `self._clock()`
        #     this class already uses everywhere else for its own
        #     "actual execution time" fields (`OrderEvent.timestamp_utc`,
        #     `Position.opened_at`, `Trade.closed_at`) — never
        #     `intent.created_at` (order-creation time, a different,
        #     already-existing field).
        self._fills.append(
            Fill(
                fill_id=self._id_factory(),
                order_id=intent.order_id,
                instrument_id=intent.instrument_id,
                side=intent.side,
                quantity=fill_quantity,
                price=slipped_price,
                timestamp=self._clock(),
                transaction_cost=cost,
                slippage_applied=slipped_price - price,
                status_at_fill=target_state,
                source=FillSource.PAPER,
            )
        )

    def _apply_to_position(
        self,
        intent: OrderIntent,
        fill_quantity: Decimal,
        fill_price: Decimal,
        fill_cost: Decimal,
    ) -> None:
        existing = self._positions.get(intent.instrument_id)
        now = self._clock()

        if existing is None or existing.status is PositionStatus.CLOSED:
            self._positions[intent.instrument_id] = Position(
                position_id=PositionId(self._id_factory()),
                instrument_id=intent.instrument_id,
                direction=intent.side,
                quantity=fill_quantity,
                average_entry_price=fill_price,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                opened_at=now,
                status=PositionStatus.OPEN,
                realized_net_pnl=Decimal("0"),
            )
            # Checkpoint 64.37: this fill's own transaction cost (already
            # charged to `_available_balance` above, in `_attempt_fill` —
            # NOT charged again here) is the entry-side cost attributable
            # to this now-open quantity, tracked for later attribution
            # when the position closes.
            self._position_entry_cost[intent.instrument_id] = fill_cost
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
                realized_net_pnl=existing.realized_net_pnl,
            )
            self._position_entry_cost[intent.instrument_id] = (
                self._position_entry_cost.get(intent.instrument_id, Decimal("0")) + fill_cost
            )
            return

        # Opposite side - closes (fully or partially) the existing position.
        closing_quantity = min(existing.quantity, fill_quantity)
        direction_sign = Decimal("1") if existing.direction is Side.BUY else Decimal("-1")
        realized = direction_sign * (fill_price - existing.average_entry_price) * closing_quantity
        new_realized = existing.realized_pnl + realized

        # Checkpoint 64.37: attribute cost to THIS closing trade only —
        # the proportional share of the still-unattributed entry cost for
        # the quantity actually being closed, plus the proportional share
        # of THIS exit fill's own cost (proportional to
        # closing_quantity/fill_quantity, so a fill that both closes and
        # would-otherwise-reverse is not over/under-attributed). Costs
        # are read here, never re-charged to `_available_balance` (that
        # charge already happened once, in `_attempt_fill`) - counted
        # exactly once.
        accumulated_entry_cost = self._position_entry_cost.get(intent.instrument_id, Decimal("0"))
        attributable_entry_cost = (
            accumulated_entry_cost * closing_quantity / existing.quantity
            if existing.quantity > 0
            else Decimal("0")
        )
        attributable_exit_cost = (
            fill_cost * closing_quantity / fill_quantity if fill_quantity > 0 else Decimal("0")
        )
        trade_transaction_cost = attributable_entry_cost + attributable_exit_cost
        trade_realized_net_pnl = compute_realized_net_pnl(realized, trade_transaction_cost)
        existing_position_net = existing.realized_net_pnl or Decimal("0")
        new_realized_net_pnl = existing_position_net + trade_realized_net_pnl

        self._trades.append(
            Trade(
                trade_id=TradeId(self._id_factory()),
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
                realized_net_pnl=trade_realized_net_pnl,
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
                realized_net_pnl=new_realized_net_pnl,
            )
            self._position_entry_cost.pop(intent.instrument_id, None)
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
                realized_net_pnl=new_realized_net_pnl,
            )
            self._position_entry_cost[intent.instrument_id] = (
                accumulated_entry_cost - attributable_entry_cost
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
