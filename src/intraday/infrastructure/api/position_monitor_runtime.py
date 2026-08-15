# File: src/intraday/infrastructure/api/position_monitor_runtime.py
#
# Checkpoint 43 Part 3/5: the stateful `PositionMonitorService` - the
# operational bridge Checkpoint 42's own gap register named as
# missing. Given the current market price for each instrument with an
# open `ManagedPosition`, evaluates `evaluate_position_exit()`
# (Checkpoint 42's pure decision logic, reused verbatim - never
# reimplemented), and for a fired `ExitDecision`: submits a REAL paper
# exit order (opposite side, exact exit quantity) through the SAME
# `PaperTradingService.submit_order()` every other order in this
# project goes through (never a broker-bypassing shortcut), then
# updates the position's lifecycle state in the durable ledger.
#
# Lives in `infrastructure/api/`, matching the established composition-
# root precedent (Decision 153/173 etc.) - this module touches
# concrete `PaperBroker`/`DjangoPaperLedgerRepository` infrastructure.
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.position.contracts import PositionStatus
from intraday.domain.shared_kernel.contracts import Side
from intraday.infrastructure.api.paper_trading_runtime import get_paper_trading_service
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.trading_engine.position_management.contracts import (
    ExitDecision,
    ExitReason,
    ManagedPosition,
    PositionLifecycleStatus,
)
from intraday.trading_engine.position_management.monitor import evaluate_position_exit

EMERGENCY_SQUARE_OFF_ACTOR = "system_emergency_square_off"


@dataclass(frozen=True, slots=True)
class PositionMonitorTickOutcome:
    positions_evaluated: int
    exits_triggered: int
    exit_decisions: tuple[ExitDecision, ...]


def run_position_monitor_tick(
    *, current_prices: dict[str, Decimal], now: datetime | None = None
) -> PositionMonitorTickOutcome:
    """`current_prices` keyed by `str(instrument_id)` - supplied by the
    caller (the market-data ingestion tick, which already has the
    latest quote for exactly the instruments it just fetched); this
    function makes no market-data call of its own, matching every
    other pure-orchestration service in this project's "caller
    supplies inputs" discipline (Checkpoint 36)."""
    clock = now or datetime.now(tz=UTC)
    ledger = DjangoPaperLedgerRepository()
    trading_service = get_paper_trading_service()

    managed_positions = ledger.load_open_managed_positions()
    exit_decisions: list[ExitDecision] = []

    for managed in managed_positions:
        current_price = current_prices.get(str(managed.position.instrument_id))
        if current_price is None:
            continue  # no fresh price for this instrument this tick - nothing to evaluate

        is_long = managed.position.direction is Side.BUY
        new_highest = (
            max(managed.highest_favorable_price, current_price)
            if is_long
            else min(managed.highest_favorable_price, current_price)
        )

        decision = evaluate_position_exit(managed=managed, current_price=current_price, now=clock)
        if decision is None:
            if new_highest != managed.highest_favorable_price:
                # No exit fired, but the trailing-stop reference price
                # still needs to advance - persisted even without an
                # exit so a LATER trailing-stop evaluation is correct.
                ledger.update_position_lifecycle(
                    position_id=str(managed.position.position_id),
                    lifecycle_status=managed.lifecycle_status,
                    remaining_quantity=managed.remaining_quantity,
                    highest_favorable_price=new_highest,
                    exit_reason="",
                )
            continue

        exit_decisions.append(decision)
        _submit_exit_order(
            trading_service=trading_service,
            managed=managed,
            decision=decision,
            clock=clock,
        )
        remaining_after = managed.remaining_quantity - decision.exit_quantity
        ledger.update_position_lifecycle(
            position_id=str(managed.position.position_id),
            lifecycle_status=decision.new_lifecycle_status,
            remaining_quantity=remaining_after,
            highest_favorable_price=new_highest,
            exit_reason=decision.reason.value,
        )

    return PositionMonitorTickOutcome(
        positions_evaluated=len(managed_positions),
        exits_triggered=len(exit_decisions),
        exit_decisions=tuple(exit_decisions),
    )


def _submit_exit_order(
    *,
    trading_service: PaperTradingService,
    managed: ManagedPosition,
    decision: ExitDecision,
    clock: datetime,
) -> None:
    exit_side = Side.SELL if managed.position.direction is Side.BUY else Side.BUY
    order = OrderIntent(
        order_id=str(uuid.uuid4()),  # type: ignore[arg-type]
        instrument_id=managed.position.instrument_id,
        side=exit_side,
        quantity=decision.exit_quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id=managed.strategy_id,
        created_at=clock,
        idempotency_key=f"exit:{decision.position_id}:{decision.reason.value}:{clock.isoformat()}",
    )
    trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=decision.exit_quantity * decision.exit_price,
        already_submitted_idempotency_keys=frozenset(),
        # Checkpoint 45 Part 6: this order can only ever SHRINK the
        # existing position (opposite side, exit_quantity <= what is
        # currently open) - never open a new one, never increase one -
        # so it must remain closable even while the kill switch is
        # engaged.
        is_position_reducing=True,
    )


@dataclass(frozen=True, slots=True)
class EmergencySquareOffOutcome:
    positions_found: int
    positions_closed: int
    positions_failed: tuple[str, ...]
    """position_id values that could not be closed - e.g. no current
    price recorded for that instrument. NEVER silently dropped - a
    failed emergency exit is exactly the kind of thing an operator
    must be told about immediately."""


def run_emergency_square_off(
    *, current_prices: dict[str, Decimal], now: datetime | None = None
) -> EmergencySquareOffOutcome:
    """Checkpoint 45 Part 6: EMERGENCY_SQUARE_OFF, distinct from
    HALT_NEW_ENTRIES (the kill switch's own existing, unchanged
    behavior - see `KillSwitchService`). Closes EVERY currently open
    broker position, unconditionally, at MARKET, regardless of whether
    that position has an `ExitPlan` attached (unlike
    `run_position_monitor_tick()`, which only monitors positions WITH
    a real exit plan - an emergency square-off must close ALL open
    exposure, plan or no plan). Each exit order is submitted with
    `is_position_reducing=True`, so it is NOT blocked by the very kill
    switch that is presumably engaged when this is called - proving
    the fix from this checkpoint's own Decision 195 in the one
    scenario it exists for.

    This function does NOT itself check or engage the kill switch -
    that remains `KillSwitchService`'s job (`HALT_NEW_ENTRIES`,
    unchanged). `run_emergency_square_off()` is the SEPARATE,
    explicit `EMERGENCY_SQUARE_OFF` action an operator (or a future
    automated EOD/kill-switch-engagement hook, not built this
    checkpoint) triggers deliberately.

    `current_prices` (keyed by `str(instrument_id)`) is CALLER-supplied
    when available - matching `run_position_monitor_tick()`'s own
    established discipline (Checkpoint 44). Checkpoint 47 Part 4 ADDS a
    fallback: when an instrument has no caller-supplied price (the
    exact scenario an independent safety trigger needs to survive -
    market-data ingestion, the USUAL price source, may itself be the
    failed subsystem an emergency square-off exists to protect
    against), this function falls back to `PaperBroker`'s own
    paper-specific `get_latest_price()` (its last recorded price,
    possibly stale, but a real, known price - never fabricated). This
    is a DELIBERATE, DOCUMENTED exception to Decision 197's broker-
    neutrality preference: `PaperBroker` is the only broker this
    project has, and an emergency mechanism that fails closed (refuses
    to close a position) purely because the abstraction is
    broker-neutral would be exactly backwards - revisit this fallback
    when a real `DhanBroker` exists and can be asked the same
    question through a shared interface method."""
    clock = now or datetime.now(tz=UTC)
    trading_service = get_paper_trading_service()
    ledger = DjangoPaperLedgerRepository()

    open_positions = [
        p for p in trading_service.broker.get_positions() if p.status is PositionStatus.OPEN
    ]
    closed = 0
    failed: list[str] = []

    for position in open_positions:
        current_price = current_prices.get(str(position.instrument_id))
        if current_price is None:
            get_latest_price = getattr(trading_service.broker, "get_latest_price", None)
            if callable(get_latest_price):
                current_price = get_latest_price(position.instrument_id)
        if current_price is None:
            failed.append(str(position.position_id))
            continue

        # Checkpoint 51: a REAL bug found while building the EOD
        # lifecycle test on top of this function - `PaperBroker.
        # submit_order()` fills a MARKET order at its OWN internally
        # recorded price (`_latest_prices`), never at anything passed
        # into `submit_order()` itself. Without this call, a
        # caller-supplied `current_price` here was silently ignored for
        # the ACTUAL fill (only used for the "can we price this at
        # all" check and the risk-evaluation notional estimate above),
        # so every emergency/EOD square-off exit silently filled at
        # whatever stale price the broker last happened to record -
        # frequently the SAME price the position was entered at,
        # producing a fabricated zero realized P&L regardless of the
        # real exit price the caller intended. `record_price()` is
        # idempotent and safe to call with the same value the fallback
        # branch above may have just read from the broker itself.
        record_price = getattr(trading_service.broker, "record_price", None)
        if callable(record_price):
            record_price(position.instrument_id, current_price, clock)

        exit_side = Side.SELL if position.direction is Side.BUY else Side.BUY
        order = OrderIntent(
            order_id=str(uuid.uuid4()),  # type: ignore[arg-type]
            instrument_id=position.instrument_id,
            side=exit_side,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id=EMERGENCY_SQUARE_OFF_ACTOR,  # type: ignore[arg-type]
            created_at=clock,
            idempotency_key=f"emergency_square_off:{position.position_id}:{clock.isoformat()}",
        )
        result = trading_service.submit_order(
            order,
            strategy_is_active=True,
            market_session_is_open=True,
            data_quality_is_stale=False,
            estimated_order_notional=position.quantity * current_price,
            already_submitted_idempotency_keys=frozenset(),
            is_position_reducing=True,
        )
        if result.broker_report is None:
            failed.append(str(position.position_id))
            continue

        ledger.update_position_lifecycle(
            position_id=str(position.position_id),
            lifecycle_status=PositionLifecycleStatus.STOPPED,
            remaining_quantity=Decimal("0"),
            highest_favorable_price=current_price,
            exit_reason=ExitReason.RISK_HALT.value,
        )
        closed += 1

    return EmergencySquareOffOutcome(
        positions_found=len(open_positions),
        positions_closed=closed,
        positions_failed=tuple(failed),
    )
