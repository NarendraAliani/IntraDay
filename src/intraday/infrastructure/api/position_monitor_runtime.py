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
from intraday.domain.shared_kernel.contracts import Side
from intraday.infrastructure.api.paper_trading_runtime import get_paper_trading_service
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.trading_engine.position_management.contracts import ExitDecision, ManagedPosition
from intraday.trading_engine.position_management.monitor import evaluate_position_exit


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
    )
