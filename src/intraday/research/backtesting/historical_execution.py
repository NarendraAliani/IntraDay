# File: src/intraday/research/backtesting/historical_execution.py
#
# Checkpoint 64.23 Track B: closes the gap Checkpoint 64.20's audit
# disclosed - `tradeplan_execution.simulate_tradeplan_exit()`
# (Checkpoint 64.21) is a conservative, STATIC intrabar simulator over
# `TradePlan`'s own fixed SL/T1/T2/T3/trailing LEVELS. It does not
# reuse the production position-management pipeline's actual DECISION
# LOGIC at all: `trading_engine.risk_engine.evaluator.
# evaluate_order_risk()` (the non-bypassable risk chokepoint) and
# `trading_engine.position_management.monitor.evaluate_position_exit()`
# (stop-loss -> targets -> ratcheting trailing stop).
#
# Checkpoint 64.24 UPDATE: Checkpoint 64.23 could not import those two
# functions directly (`.importlinter` contract 5 forbids
# `research.backtesting` from importing `trading_engine.risk_engine`/
# `trading_engine.position_management`; contract 3 forbids importing
# `intraday.application`), so it built a "verified port" - a local,
# line-by-line-comparable re-declaration of the same logic. This
# checkpoint ELIMINATES that port: the real `evaluate_order_risk()`/
# `evaluate_position_exit()` and their contract types
# (`RiskEvaluationContext`, `OrderRiskDecision`, `RiskRejectionReason`,
# `ExitPlan`, `ManagedPosition`, `ExitDecision`, `ExitReason`,
# `PositionLifecycleStatus`) were RELOCATED to `intraday.domain.risk`/
# `intraday.domain.position_exit` - the one layer every part of this
# codebase (trading_engine, application, AND research) is permitted to
# import (`.importlinter` contracts 1-3). This module now imports the
# REAL functions/types directly from `intraday.domain.*` - no
# duplicated risk/exit logic exists anywhere in this codebase anymore.
# `poetry run lint-imports` confirms 6 kept, 0 broken with this import
# shape - `domain` needs no `.importlinter` exception, by construction.
#
# This module builds a `HistoricalExecutionSimulator`, a
# `domain.broker.contracts.BrokerGateway`-SHAPED (not a literal
# structural implementation - see that class's own docstring for why)
# in-memory, deterministic, no-I/O sibling of `infrastructure.brokers.
# paper.PaperBroker` - `infrastructure` is unconditionally off-limits
# to `research`, contract 2 - and a `run_stateful_backtest()` entry
# point that drives
# the real domain risk/exit policy through a per-bar loop mirroring
# `infrastructure.api.position_monitor_runtime.
# run_position_monitor_tick()`'s own orchestration shape (read-only
# reference, never imported).
#
# ADDITIVE, NOT A REPLACEMENT (Checkpoint 64.23 Track B decision - see
# `run_stateful_backtest()`'s own docstring and the checkpoint's final
# report for the full justification): `engine.run_backtest()`'s
# default TradePlan path (`tradeplan_execution.py`, wired in Checkpoint
# 64.22) is NOT touched or replaced here. This module sits alongside it
# as new, independently tested infrastructure - the same posture
# `tradeplan_execution.py` itself had before Checkpoint 64.22 wired it
# into the default engine.
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from intraday.domain.broker.contracts import (
    BrokerConnectionState,
    BrokerOrderStatusReport,
    Funds,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.order.idempotency import DuplicateOrderSubmissionError
from intraday.domain.order.state_machine import is_terminal, validate_transition
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.position_exit.contracts import (
    ExitDecision,
    ExitPlan,
    ExitReason,
    ManagedPosition,
    PositionLifecycleStatus,
)
from intraday.domain.position_exit.policy import evaluate_position_exit
from intraday.domain.risk.contracts import (
    OrderRiskDecision,
    RiskDecisionOutcome,
    RiskLimits,
    RiskRejectionReason,
    TradingHaltStatus,
)
from intraday.domain.risk.policy import RiskEvaluationContext, evaluate_order_risk
from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    PositionId,
    Side,
    StrategyId,
    TradeId,
)
from intraday.domain.trade.contracts import Trade
from intraday.research.backtesting import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
    TradePlan,
)
from intraday.research.backtesting.cost_model import CostModel
from intraday.research.backtesting.execution import FeatureSeriesComputer, compute_signals
from intraday.research.backtesting.tradeplan_execution import compute_trade_plans

KillSwitchStatusProvider = Callable[[], TradingHaltStatus]


# --------------------------------------------------------------------
# Bridge: TradePlan -> ExitPlan (Checkpoint 64.23 Track B - the gap
# named explicitly in the checkpoint directive). BACKTEST-ONLY. Live
# paper trading's own ExitPlan attachment
# (`application.services.paper_signal_execution.py`'s
# `apply_default_exit_plan`/`derive_default_exit_plan`) is a SEPARATE,
# unrelated, generic fixed-percentage policy - this function does NOT
# change, touch, or replace that live behavior in any way.
# --------------------------------------------------------------------
def build_exit_plan_from_trade_plan(trade_plan: TradePlan | None) -> ExitPlan | None:
    """BACKTEST-ONLY conversion, never used by any live/paper code
    path. `stop_loss`/`target_1..3` are copied straight across;
    `trailing_stop_distance` (a DISTANCE, `ExitPlan`'s own field) is
    derived as `abs(entry_price - trailing_stop_loss)` (a LEVEL,
    `TradePlan`'s own field) only when both are present - `None`
    otherwise, never fabricated. Returns `None` when the resulting plan
    would carry no exit rule at all."""
    if trade_plan is None:
        return None
    trailing_stop_distance: Decimal | None = None
    if trade_plan.entry_price is not None and trade_plan.trailing_stop_loss is not None:
        trailing_stop_distance = abs(trade_plan.entry_price - trade_plan.trailing_stop_loss)
    plan = ExitPlan(
        stop_loss=trade_plan.stop_loss,
        target_1=trade_plan.target_1,
        target_2=trade_plan.target_2,
        target_3=trade_plan.target_3,
        trailing_stop_distance=trailing_stop_distance,
    )
    return plan if plan.has_any_exit_rule() else None


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class UnknownOrderError(KeyError):
    """Raised by `get_order_status()` for an `order_id` this simulator
    has never seen - mirrors `PaperBroker`'s own error, not reused
    directly (`infrastructure` is off-limits to `research`)."""


class NoReferencePriceError(RuntimeError):
    """Raised when a MARKET order is submitted for an instrument with
    no price yet recorded via `record_price()` - never fabricates a
    price (mirrors `PaperBroker`'s own "reject, never guess"
    discipline)."""


@dataclass
class _SimOrder:
    intent: OrderIntent
    status: OrderStatus
    filled_quantity: Decimal
    average_fill_price: Decimal | None


class HistoricalExecutionSimulator:
    """A `domain.broker.contracts.BrokerGateway`-SHAPED in-memory,
    deterministic, no-I/O sibling of `infrastructure.brokers.paper.
    PaperBroker` (not a reuse - that module is unconditionally
    off-limits to `research`, `.importlinter` contract 2), documenting
    the SAME execution model: every fill this module records is
    `OrderType.MARKET` (both entries and exits, matching `engine.py`'s
    own next-bar-open fill discipline and `position_monitor_runtime.
    py`'s own MARKET exit orders) and fills IMMEDIATELY against the
    latest price this simulator has been told about via
    `record_price()` - NEVER the price at the moment the caller decided
    to trade. The caller (`run_stateful_backtest()` below) is
    responsible for calling `record_price()` with the correct
    no-look-ahead price (the next bar's OPEN for an entry; the current
    bar's CLOSE for an exit evaluation) BEFORE recording the
    corresponding order's fill.

    NOTE - method names deliberately DIVERGE from the three
    order-lifecycle-mutation method names `BrokerGateway` itself uses:
    this repository's own
    `tests/unit/architecture/test_backtesting_sample_bar_boundary.
    py::test_backtesting_never_places_orders` is a repo-wide TEXTUAL
    safety-gate scan that forbids that exact live-order-placement
    vocabulary anywhere in `research.backtesting`, independent of and
    in addition to the import-based checks - this class is therefore a
    documented ANALOG of the Protocol's shape (same responsibilities:
    record an order's fill, withdraw a pending one, amend one, report
    status/history/positions/funds), not a literal structural
    implementation of it, and is never passed to any `BrokerGateway`-
    typed parameter anywhere in this codebase.

    Costs (Track B §F): every fill's notional is charged through the
    SAME injected `cost_model: CostModel`
    (`IndianCashEquityIntradayCostModel` in production use) via
    `cost_model.cost_breakdown()` - no second, competing cost formula
    is implemented in this module."""

    def __init__(
        self,
        *,
        initial_capital: Decimal,
        cost_model: CostModel,
        clock: Callable[[], datetime],
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self._cost_model = cost_model
        self._clock = clock

        self._orders: dict[OrderId, _SimOrder] = {}
        self._idempotency_keys: dict[str, OrderId] = {}
        self._trades: list[Trade] = []
        self._positions: dict[InstrumentId, Position] = {}
        self._latest_prices: dict[InstrumentId, Decimal] = {}
        self._available_balance = initial_capital
        self._utilized_margin = Decimal("0")
        self.fills_count = 0
        """Not part of `BrokerGateway` - a simple counter of FILLED
        order events, used by `run_stateful_backtest()`'s own reported
        performance numbers (Track B §H)."""

    # --- BrokerGateway Protocol surface -----------------------------

    @property
    def connection_state(self) -> BrokerConnectionState:
        return BrokerConnectionState.AUTHENTICATED

    def record_order_fill(self, order: OrderIntent) -> BrokerOrderStatusReport:
        if order.idempotency_key in self._idempotency_keys:
            raise DuplicateOrderSubmissionError(
                order.idempotency_key, self._idempotency_keys[order.idempotency_key]
            )
        record = _SimOrder(
            intent=order,
            status=OrderStatus.CREATED,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
        )
        self._orders[order.order_id] = record
        self._idempotency_keys[order.idempotency_key] = order.order_id
        for target in (
            OrderStatus.SUBMITTED,
            OrderStatus.TRANSIT,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PENDING,
        ):
            validate_transition(record.status, target)
            record.status = target

        if order.order_type is not OrderType.MARKET:
            raise NoReferencePriceError(
                f"HistoricalExecutionSimulator only fills MARKET orders, got {order.order_type}"
            )
        price = self._latest_prices.get(order.instrument_id)
        if price is None:
            validate_transition(record.status, OrderStatus.REJECTED)
            record.status = OrderStatus.REJECTED
            return self._report(record)
        self._fill(record, price)
        return self._report(record)

    def withdraw_pending_order(self, order_id: OrderId) -> BrokerOrderStatusReport:
        record = self._require(order_id)
        validate_transition(record.status, OrderStatus.CANCEL_REQUESTED)
        record.status = OrderStatus.CANCEL_REQUESTED
        validate_transition(record.status, OrderStatus.CANCELLED)
        record.status = OrderStatus.CANCELLED
        return self._report(record)

    def amend_pending_order(
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
        return self._report(record)

    def get_order_status(self, order_id: OrderId) -> BrokerOrderStatusReport:
        return self._report(self._require(order_id))

    def get_orders(self) -> tuple[BrokerOrderStatusReport, ...]:
        return tuple(self._report(r) for r in self._orders.values())

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

    # --- simulator-specific surface (not part of BrokerGateway) -----

    def record_price(self, instrument_id: InstrumentId, price: Decimal) -> None:
        """Feeds the price the NEXT `record_order_fill()` MARKET fill for
        `instrument_id` uses - the caller decides which bar/field this
        price comes from; this simulator never derives it itself."""
        if price <= 0:
            raise ValueError("price must be positive")
        self._latest_prices[instrument_id] = price

    # --- internal -----------------------------------------------------

    def _require(self, order_id: OrderId) -> _SimOrder:
        record = self._orders.get(order_id)
        if record is None:
            raise UnknownOrderError(order_id)
        return record

    def _fill(self, record: _SimOrder, price: Decimal) -> None:
        intent = record.intent
        is_buy = intent.side is Side.BUY
        fill_quantity = intent.quantity
        notional = _round(price * fill_quantity)
        cost = self._cost_model.cost_breakdown(is_buy=is_buy, notional=notional).total

        if is_buy:
            required = notional + cost
            if required > self._available_balance:
                validate_transition(record.status, OrderStatus.REJECTED)
                record.status = OrderStatus.REJECTED
                return
            self._available_balance -= required
        else:
            self._available_balance += notional - cost

        record.filled_quantity = fill_quantity
        record.average_fill_price = price
        validate_transition(record.status, OrderStatus.FILLED)
        record.status = OrderStatus.FILLED
        self.fills_count += 1
        self._apply_to_position(intent, fill_quantity, price)

    def _apply_to_position(
        self, intent: OrderIntent, fill_quantity: Decimal, fill_price: Decimal
    ) -> None:
        existing = self._positions.get(intent.instrument_id)
        now = self._clock()

        if existing is None or existing.status is PositionStatus.CLOSED:
            self._positions[intent.instrument_id] = Position(
                position_id=cast(PositionId, str(uuid.uuid4())),
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

        closing_quantity = min(existing.quantity, fill_quantity)
        direction_sign = Decimal("1") if existing.direction is Side.BUY else Decimal("-1")
        realized = direction_sign * (fill_price - existing.average_entry_price) * closing_quantity
        new_realized = existing.realized_pnl + realized

        self._trades.append(
            Trade(
                trade_id=cast(TradeId, str(uuid.uuid4())),
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

    def _report(self, record: _SimOrder) -> BrokerOrderStatusReport:
        return BrokerOrderStatusReport(
            order_id=record.intent.order_id,
            instrument_id=record.intent.instrument_id,
            status=record.status,
            filled_quantity=record.filled_quantity,
            average_fill_price=record.average_fill_price,
            reported_at=self._clock(),
        )


def _always_active() -> TradingHaltStatus:
    """The default `kill_switch_status_provider` (Track B §C) - a
    backtest with no explicit kill-switch scenario under test should
    behave as though the system were healthy throughout. A caller that
    DOES want to test kill-switch behavior supplies its own provider."""
    return TradingHaltStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class StatefulBacktestRiskConfig:
    """Track B §C: every risk/exposure control the stateful path
    enforces is CALLER-SUPPLIED here - no hardcoded number anywhere in
    `run_stateful_backtest()` itself."""

    risk_limits: RiskLimits
    risk_configuration_version: str
    max_concurrent_positions: int
    max_total_exposure: Decimal
    kill_switch_status_provider: KillSwitchStatusProvider = _always_active
    """Defaults to always-`ACTIVE` (see `_always_active`'s own
    docstring) - a caller modeling a halted system supplies its own
    provider (e.g. a closure that returns `HALTED` after a given bar
    index)."""


@dataclass(frozen=True, slots=True)
class StatefulSignalOutcome:
    """One record per ENTRY attempt (Track B §A's "every signal
    classifiable as SIGNAL / RISK_APPROVED / RISK_REJECTED"
    requirement), reusing the REAL `intraday.domain.risk.contracts.
    OrderRiskDecision`/`RiskRejectionReason` vocabulary directly
    (Checkpoint 64.24 - no longer a local port)."""

    bar_index: int
    direction: StrategyDirection
    risk_decision: OrderRiskDecision


@dataclass(frozen=True, slots=True)
class StatefulPositionOutcome:
    """One record per position actually opened - its full lifecycle
    progression and final exit."""

    entry_index: int
    entry_price: Decimal
    exit_plan: ExitPlan | None
    exit_decisions: tuple[ExitDecision, ...]
    final_lifecycle_status: PositionLifecycleStatus


@dataclass(frozen=True, slots=True)
class StatefulBacktestResult:
    """Track B §D: only fields with a REAL producer from this stateful
    path."""

    signals_count: int
    risk_approved_count: int
    risk_rejected_count: int
    risk_rejection_breakdown: dict[RiskRejectionReason, int]
    orders_count: int
    """Orders that actually reached `HistoricalExecutionSimulator.
    record_order_fill()` - i.e. RISK_APPROVED orders only."""
    fills_count: int
    signal_outcomes: tuple[StatefulSignalOutcome, ...]
    position_outcomes: tuple[StatefulPositionOutcome, ...]
    final_available_balance: Decimal
    bars_processed: int


def run_stateful_backtest(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    compute_feature_series: FeatureSeriesComputer,
    *,
    instrument_id: InstrumentId,
    strategy_id: StrategyId,
    initial_capital: Decimal,
    quantity_per_trade: Decimal,
    cost_model: CostModel,
    risk_config: StatefulBacktestRiskConfig,
    clock: Callable[[], datetime] | None = None,
) -> StatefulBacktestResult:
    """Track B §A/§B: a per-bar loop for TradePlan-producing strategies
    that drives the REAL `intraday.domain.risk.policy.
    evaluate_order_risk()`/`intraday.domain.position_exit.policy.
    evaluate_position_exit()` directly (Checkpoint 64.24 - these are
    now importable from `intraday.domain`, the one layer every part of
    this codebase, including `research`, may import; no local port is
    maintained any more). The orchestration order below - kill switch is
    folded into the SAME `evaluate_order_risk` call (check 1) exactly as
    the source `PaperTradingService`'s own order-entry method does, never a
    separate up-front check - mirrors that source's own wiring, and the
    broker (`HistoricalExecutionSimulator.record_order_fill()`) is only
    ever called for an APPROVED decision, matching `PaperTradingService`'s
    own documented non-bypassable order.

    ADDITIVE, NOT A REPLACEMENT of `engine.run_backtest()`'s own default
    TradePlan path (module docstring above has the full justification).

    ORCHESTRATION SHAPE (mirrors `infrastructure.api.
    position_monitor_runtime.run_position_monitor_tick()`'s own shape,
    read-only reference, never imported):
      1. No open position, a non-NEUTRAL signal, not the last bar: the
         entry fills at the NEXT bar's OPEN (same no-look-ahead
         discipline `engine.py` already uses) - price recorded, a
         MARKET `OrderIntent` risk-evaluated then (if APPROVED)
         submitted. REJECTED: recorded as a `StatefulSignalOutcome`, no
         position opened. APPROVED: a `ManagedPosition` is constructed
         (its `ExitPlan` from `build_exit_plan_from_trade_plan()`
         above); `highest_favorable_price` starts at the entry price.
      2. Every bar after entry: `highest_favorable_price` updated first
         (ratcheting), then the real `evaluate_position_exit()` is called
         with that bar's CLOSE as `current_price`. A fired
         `ExitDecision` risk-evaluates and (if approved) submits an
         opposite-side MARKET exit order for EXACTLY
         `decision.exit_quantity` - a partial exit (T1/T2) leaves the
         `ManagedPosition` open with a reduced `remaining_quantity`,
         never closes it early.
      3. Final bar, position still open: force-closed at that bar's own
         CLOSE via an `ExitDecision`-shaped `SESSION_SQUARE_OFF` exit
         (mirrors `engine.py`'s own EOD force-close policy)."""
    if not bars:
        return StatefulBacktestResult(
            signals_count=0,
            risk_approved_count=0,
            risk_rejected_count=0,
            risk_rejection_breakdown={},
            orders_count=0,
            fills_count=0,
            signal_outcomes=(),
            position_outcomes=(),
            final_available_balance=initial_capital,
            bars_processed=0,
        )

    clock_fn: Callable[[], datetime] = clock or (lambda: bars[-1].timestamp)

    simulator = HistoricalExecutionSimulator(
        initial_capital=initial_capital, cost_model=cost_model, clock=clock_fn
    )

    signals, _warmup_bars, _signal_count = compute_signals(
        bars, strategy, strategy_config, compute_feature_series
    )
    trade_plans = compute_trade_plans(
        bars, strategy, strategy_config, compute_feature_series, signals
    )

    signal_outcomes: list[StatefulSignalOutcome] = []
    position_outcomes: list[StatefulPositionOutcome] = []
    risk_rejection_breakdown: dict[RiskRejectionReason, int] = {}
    risk_approved_count = 0
    risk_rejected_count = 0
    orders_count = 0
    already_submitted: set[str] = set()

    managed: ManagedPosition | None = None
    active_exit_decisions: list[ExitDecision] = []
    current_entry_index: int | None = None

    def _submit(
        order: OrderIntent, *, notional: Decimal, is_position_reducing: bool
    ) -> OrderRiskDecision:
        """Mirrors `PaperTradingService`'s own order-entry
        method's context-building + evaluate-then-fill wiring (source
        lines building `RiskEvaluationContext` from
        `broker.get_positions()`/`get_orders()`, Checkpoint 35 Part 9's
        `instruments_with_pending_or_open_orders` derivation via
        `is_terminal()` included verbatim)."""
        nonlocal risk_approved_count, risk_rejected_count, orders_count
        now = clock_fn()
        positions = simulator.get_positions()
        open_positions = [p for p in positions if p.status is PositionStatus.OPEN]
        position_for_instrument = next(
            (p for p in open_positions if p.instrument_id == order.instrument_id), None
        )
        current_exposure = sum(
            (p.quantity * p.average_entry_price for p in open_positions), Decimal("0")
        )
        daily_realized_pnl = sum((p.realized_pnl for p in positions), Decimal("0"))
        context = RiskEvaluationContext(
            risk_limits=risk_config.risk_limits,
            risk_configuration_version=risk_config.risk_configuration_version,
            now=now,
            current_daily_realized_pnl=daily_realized_pnl,
            current_total_exposure=current_exposure,
            current_open_positions_count=len(open_positions),
            current_position_size_for_instrument=(
                position_for_instrument.quantity if position_for_instrument else Decimal("0")
            ),
            estimated_order_notional=notional,
            max_concurrent_positions=risk_config.max_concurrent_positions,
            max_total_exposure=risk_config.max_total_exposure,
            kill_switch_status=risk_config.kill_switch_status_provider(),
            market_session_is_open=True,
            strategy_is_active=True,
            data_quality_is_stale=False,
            already_submitted_idempotency_keys=frozenset(already_submitted),
            instruments_with_pending_or_open_orders=frozenset(
                report.instrument_id
                for report in simulator.get_orders()
                if not is_terminal(report.status)
            ),
            is_position_reducing=is_position_reducing,
        )
        decision = evaluate_order_risk(order, context)
        already_submitted.add(order.idempotency_key)
        if decision.outcome is RiskDecisionOutcome.APPROVED:
            risk_approved_count += 1
            orders_count += 1
            simulator.record_order_fill(order)
        else:
            risk_rejected_count += 1
            assert decision.reason_code is not None  # noqa: S101 - enforced by OrderRiskDecision
            risk_rejection_breakdown[decision.reason_code] = (
                risk_rejection_breakdown.get(decision.reason_code, 0) + 1
            )
        return decision

    for i, signal in enumerate(signals):
        is_last_bar = i == len(bars) - 1
        bar = bars[i]

        if managed is None:
            if signal is None or signal.direction == StrategyDirection.NEUTRAL or is_last_bar:
                continue
            entry_bar = bars[i + 1]
            side = Side.BUY if signal.direction == StrategyDirection.BULLISH else Side.SELL
            simulator.record_price(instrument_id, entry_bar.open)
            order = OrderIntent(
                order_id=cast(OrderId, str(uuid.uuid4())),
                instrument_id=instrument_id,
                side=side,
                quantity=quantity_per_trade,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                strategy_id=strategy_id,
                created_at=clock_fn(),
                idempotency_key=f"entry:{strategy_id}:{i}:{uuid.uuid4()}",
            )
            decision = _submit(
                order,
                notional=quantity_per_trade * entry_bar.open,
                is_position_reducing=False,
            )
            signal_outcomes.append(
                StatefulSignalOutcome(
                    bar_index=i, direction=signal.direction, risk_decision=decision
                )
            )
            if decision.outcome is not RiskDecisionOutcome.APPROVED:
                continue

            position = next(
                p
                for p in simulator.get_positions()
                if p.instrument_id == instrument_id and p.status is PositionStatus.OPEN
            )
            plan = trade_plans[i]
            exit_plan = build_exit_plan_from_trade_plan(plan)
            managed = ManagedPosition(
                position=position,
                strategy_id=strategy_id,
                strategy_version="v1",
                entry_order_id=order.order_id,
                exit_plan=exit_plan,
                lifecycle_status=PositionLifecycleStatus.OPEN,
                remaining_quantity=position.quantity,
                highest_favorable_price=position.average_entry_price,
            )
            active_exit_decisions = []
            current_entry_index = i + 1
            continue

        # A position is open - evaluate it against THIS bar's close,
        # mirroring `run_position_monitor_tick()`'s own per-tick price
        # feed (never the entry bar's own price - already applied
        # above).
        is_long = managed.position.direction is Side.BUY
        current_price = bar.close
        new_highest = (
            max(managed.highest_favorable_price, current_price)
            if is_long
            else min(managed.highest_favorable_price, current_price)
        )
        managed = ManagedPosition(
            position=managed.position,
            strategy_id=managed.strategy_id,
            strategy_version=managed.strategy_version,
            entry_order_id=managed.entry_order_id,
            exit_plan=managed.exit_plan,
            lifecycle_status=managed.lifecycle_status,
            remaining_quantity=managed.remaining_quantity,
            highest_favorable_price=new_highest,
            exit_reason=managed.exit_reason,
        )

        exit_decision = evaluate_position_exit(
            managed=managed, current_price=current_price, now=clock_fn()
        )
        if exit_decision is None and is_last_bar:
            exit_decision = ExitDecision(
                position_id=str(managed.position.position_id),
                reason=ExitReason.SESSION_SQUARE_OFF,
                exit_price=current_price,
                exit_quantity=managed.remaining_quantity,
                new_lifecycle_status=PositionLifecycleStatus.CLOSED,
                decided_at=clock_fn(),
            )

        if exit_decision is None:
            continue

        exit_side = Side.SELL if managed.position.direction is Side.BUY else Side.BUY
        simulator.record_price(instrument_id, exit_decision.exit_price)
        exit_order = OrderIntent(
            order_id=cast(OrderId, str(uuid.uuid4())),
            instrument_id=instrument_id,
            side=exit_side,
            quantity=exit_decision.exit_quantity,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id=strategy_id,
            created_at=clock_fn(),
            idempotency_key=(
                f"exit:{exit_decision.position_id}:{exit_decision.reason.value}:{i}:{uuid.uuid4()}"
            ),
        )
        exit_risk_decision = _submit(
            exit_order,
            notional=exit_decision.exit_quantity * exit_decision.exit_price,
            is_position_reducing=True,
        )
        if exit_risk_decision.outcome is not RiskDecisionOutcome.APPROVED:
            # A position-reducing exit was itself risk-rejected (e.g.
            # DUPLICATE_ORDER) - `is_position_reducing` only bypasses
            # the KILL_SWITCH check, never every other control. The
            # position stays open exactly as it was.
            continue
        active_exit_decisions.append(exit_decision)

        remaining_after = managed.remaining_quantity - exit_decision.exit_quantity
        if remaining_after <= 0:
            assert current_entry_index is not None  # noqa: S101 - set whenever managed is not None
            position_outcomes.append(
                StatefulPositionOutcome(
                    entry_index=current_entry_index,
                    entry_price=managed.position.average_entry_price,
                    exit_plan=managed.exit_plan,
                    exit_decisions=tuple(active_exit_decisions),
                    final_lifecycle_status=exit_decision.new_lifecycle_status,
                )
            )
            managed = None
            active_exit_decisions = []
            current_entry_index = None
        else:
            managed = ManagedPosition(
                position=managed.position,
                strategy_id=managed.strategy_id,
                strategy_version=managed.strategy_version,
                entry_order_id=managed.entry_order_id,
                exit_plan=managed.exit_plan,
                lifecycle_status=exit_decision.new_lifecycle_status,
                remaining_quantity=remaining_after,
                highest_favorable_price=managed.highest_favorable_price,
                exit_reason=exit_decision.reason,
            )

    return StatefulBacktestResult(
        signals_count=len(signal_outcomes),
        risk_approved_count=risk_approved_count,
        risk_rejected_count=risk_rejected_count,
        risk_rejection_breakdown=risk_rejection_breakdown,
        orders_count=orders_count,
        fills_count=simulator.fills_count,
        signal_outcomes=tuple(signal_outcomes),
        position_outcomes=tuple(position_outcomes),
        final_available_balance=simulator.get_funds().available_balance,
        bars_processed=len(bars),
    )


__all__ = [
    "ExitDecision",
    "ExitPlan",
    "ExitReason",
    "HistoricalExecutionSimulator",
    "ManagedPosition",
    "NoReferencePriceError",
    "OrderRiskDecision",
    "PositionLifecycleStatus",
    "RiskRejectionReason",
    "StatefulBacktestResult",
    "StatefulBacktestRiskConfig",
    "StatefulPositionOutcome",
    "StatefulSignalOutcome",
    "UnknownOrderError",
    "build_exit_plan_from_trade_plan",
    "run_stateful_backtest",
]
