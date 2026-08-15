# File: src/intraday/infrastructure/persistence/paper_ledger_repository.py
#
# Checkpoint 35 Part 3: automatic, durable persistence for the paper-
# trading ledger. `PaperBroker` itself (Checkpoint 34) is deliberately
# Django-free and in-memory - this repository is the ONE place that
# projects its reported state into the durable `PaperOrderRecord`/
# `PaperTradeRecord`/`PaperPositionRecord`/`PaperFundsRecord` tables
# (migration 0010), keeping Order/Trade/Position/Funds as four
# distinct tables, never collapsed into one (Part 3's explicit
# instruction, carried over from Checkpoint 34 Part 12).
#
# Design: `sync_snapshot()` always writes the FULL CURRENT state the
# broker reports - order, its event history, every trade, every
# position, funds - inside one atomic transaction, upserted by natural
# key (order_id/trade_id/position_id, funds is a singleton). This is
# deliberately idempotent: calling it twice with the same broker state
# produces the same rows (proven by
# `test_duplicate_sync_is_idempotent`), and calling it after a genuine
# state change correctly updates existing rows rather than duplicating
# them - matching this project's own established "local database is a
# cache/projection of the authoritative broker state" principle
# (Decision 146, Checkpoint 33/34).
from __future__ import annotations

from django.db import transaction

from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.order.contracts import OrderIntent, OrderStatus
from intraday.domain.order.events import OrderEvent
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    PositionId,
    Side,
    TradeId,
)
from intraday.domain.trade.contracts import Trade
from intraday.infrastructure.persistence.models import (
    PaperFundsRecord,
    PaperOrderRecord,
    PaperPositionRecord,
    PaperTradeRecord,
)
from intraday.trading_engine.position_management.contracts import (
    ExitPlan,
    ManagedPosition,
    PositionLifecycleStatus,
)


def _event_to_dict(event: OrderEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "correlation_id": event.correlation_id,
        "timestamp_utc": event.timestamp_utc.isoformat(),
        "received_at_utc": event.received_at_utc.isoformat(),
        "previous_state": event.previous_state.value if event.previous_state else None,
        "new_state": event.new_state.value,
        "quantity": str(event.quantity),
        "filled_quantity": str(event.filled_quantity),
        "remaining_quantity": str(event.remaining_quantity),
        "price": str(event.price) if event.price is not None else None,
    }


class DjangoPaperLedgerRepository:
    """Django ORM implementation of the paper-ledger persistence
    surface. Never mutates `PaperBroker`'s own in-memory state - reads
    only, writes only to the durable tables."""

    @transaction.atomic
    def sync_order(
        self,
        *,
        order: OrderIntent,
        report: BrokerOrderStatusReport,
        correlation_id: str,
        events: tuple[OrderEvent, ...],
    ) -> None:
        PaperOrderRecord.objects.update_or_create(
            order_id=str(order.order_id),
            defaults={
                "idempotency_key": order.idempotency_key,
                "correlation_id": correlation_id,
                "instrument_id": str(order.instrument_id),
                "strategy_id": str(order.strategy_id),
                "signal_id": str(order.signal_id) if order.signal_id else "",
                "side": order.side.value,
                "order_type": order.order_type.value,
                "quantity": order.quantity,
                "filled_quantity": report.filled_quantity,
                "limit_price": order.limit_price,
                "trigger_price": order.trigger_price,
                "status": report.status.value,
                "created_at": order.created_at,
                "state_history": [_event_to_dict(e) for e in events],
            },
        )

    @transaction.atomic
    def sync_trades(self, trades: tuple[Trade, ...]) -> None:
        for trade in trades:
            PaperTradeRecord.objects.update_or_create(
                trade_id=str(trade.trade_id),
                defaults={
                    "strategy_id": str(trade.strategy_id),
                    "instrument_id": str(trade.instrument_id),
                    "direction": trade.direction.value,
                    "order_ids": [str(oid) for oid in trade.order_ids],
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "realized_pnl": trade.realized_pnl,
                    "opened_at": trade.opened_at,
                    "closed_at": trade.closed_at,
                },
            )

    @transaction.atomic
    def sync_positions(self, positions: tuple[Position, ...]) -> None:
        for position in positions:
            PaperPositionRecord.objects.update_or_create(
                position_id=str(position.position_id),
                defaults={
                    "instrument_id": str(position.instrument_id),
                    "direction": position.direction.value,
                    "quantity": position.quantity,
                    "average_entry_price": position.average_entry_price,
                    "realized_pnl": position.realized_pnl,
                    "unrealized_pnl": position.unrealized_pnl,
                    "opened_at": position.opened_at,
                    "closed_at": position.closed_at,
                    "status": position.status.value,
                },
            )

    @transaction.atomic
    def sync_funds(self, funds: Funds) -> None:
        PaperFundsRecord.objects.update_or_create(
            pk=1,
            defaults={
                "available_balance": funds.available_balance,
                "utilized_margin": funds.utilized_margin,
            },
        )

    @transaction.atomic
    def sync_snapshot(
        self,
        *,
        order: OrderIntent,
        report: BrokerOrderStatusReport,
        correlation_id: str,
        events: tuple[OrderEvent, ...],
        trades: tuple[Trade, ...],
        positions: tuple[Position, ...],
        funds: Funds,
    ) -> None:
        """The one call site `PaperTradingService` uses after every
        broker mutation - persists the order, every trade, every
        position, and the funds snapshot together, in one transaction,
        so a crash between writes can never leave the durable ledger
        internally inconsistent."""
        self.sync_order(order=order, report=report, correlation_id=correlation_id, events=events)
        self.sync_trades(trades)
        self.sync_positions(positions)
        self.sync_funds(funds)

    @transaction.atomic
    def patch_order_status(
        self,
        *,
        order_id: str,
        status: str,
        filled_quantity: object,
        events: tuple[OrderEvent, ...],
    ) -> None:
        """Checkpoint 35 Part 7: updates only the status/fill/event-history
        fields of an ALREADY-PERSISTED order row (created by an earlier
        `sync_order()` call at submission time) - used by the end-of-
        session expiry path, which has a `BrokerOrderStatusReport` (not
        a full `OrderIntent`) to work from. A no-op (does not create a
        new row) if the order was never persisted in the first place -
        expiry never fabricates order history."""
        PaperOrderRecord.objects.filter(order_id=order_id).update(
            status=status,
            filled_quantity=filled_quantity,
            state_history=[_event_to_dict(e) for e in events],
        )

    def load_order_status_by_id(self) -> dict[OrderId, str]:
        """Checkpoint 35 Part 3: reload every persisted order's status
        - proves the durable ledger, not `PaperBroker`'s in-memory
        state, is what survives a process restart."""
        return {OrderId(row.order_id): row.status for row in PaperOrderRecord.objects.all()}

    def load_processed_signal_ids(self) -> frozenset[str]:
        """Checkpoint 39 Part F: the RESTART-SAFE half of idempotent
        strategy triggering. `PaperSignalExecutionService.
        evaluate_and_submit()`'s own `already_processed_signal_ids`
        parameter (Checkpoint 36) only prevents duplicates within a
        single caller's in-memory set - across a process restart, that
        set is empty again. This method reloads every `signal_id` that
        already produced a persisted order, so a caller (a scheduler
        task, Checkpoint 39) can pass a RESTART-SURVIVING dedup set on
        every invocation, closing the "restart does not duplicate
        processing" requirement with real persisted evidence, not an
        in-memory assumption. Blank `signal_id`s (manually-submitted
        orders, Checkpoint 36) are excluded - they were never a
        strategy-generated signal to begin with."""
        return frozenset(
            PaperOrderRecord.objects.exclude(signal_id="").values_list("signal_id", flat=True)
        )

    def load_order_statuses_for_reconciliation(self) -> dict[OrderId, OrderStatus]:
        """Checkpoint 38 Part 13: the "local expected state" half of
        paper-mode reconciliation - the SAME shape
        `control_plane.reconciliation.reconcile_orders()` already
        requires (`dict[OrderId, OrderStatus]`), so that function is
        reused verbatim, never re-implemented for the paper broker."""
        return {
            OrderId(row.order_id): OrderStatus(row.status) for row in PaperOrderRecord.objects.all()
        }

    def load_trades_for_reconciliation(self) -> dict[TradeId, Trade]:
        result: dict[TradeId, Trade] = {}
        for row in PaperTradeRecord.objects.all():
            trade_id = TradeId(row.trade_id)
            result[trade_id] = Trade(
                trade_id=trade_id,
                strategy_id=row.strategy_id,  # type: ignore[arg-type]
                instrument_id=InstrumentId(row.instrument_id),
                direction=Side(row.direction),
                order_ids=tuple(OrderId(oid) for oid in row.order_ids),
                entry_price=row.entry_price,
                exit_price=row.exit_price,
                quantity=row.quantity,
                realized_pnl=row.realized_pnl,
                opened_at=row.opened_at,
                closed_at=row.closed_at,
            )
        return result

    def load_positions_for_reconciliation(self) -> dict[str, Position]:
        """Keyed by `instrument_id` string, matching
        `reconcile_positions()`'s own expected key shape - one position
        per instrument.

        Checkpoint 47 Part 2 ROOT-CAUSE FIX: this method used to filter
        `status="OPEN"` only, while `PaperBroker.get_positions()` (the
        `broker` side `reconcile_positions()` compares against) reports
        EVERY position it has ever held, open or closed
        (`infrastructure/brokers/paper/broker.py::get_positions()`
        returns `tuple(self._positions.values())` unconditionally).
        The mismatch produced a real, reproducible `MISSING_LOCALLY`
        divergence for every position the moment it closed - found by
        Checkpoint 46's own end-to-end emergency-square-off test, left
        unresolved there, root-caused and fixed here. Ordered by `pk`
        (insertion order) so the dict-overwrite-by-instrument below
        naturally keeps the MOST RECENT row per instrument, matching
        `PaperBroker`'s own single-entry-per-instrument dict."""
        result: dict[str, Position] = {}
        for row in PaperPositionRecord.objects.order_by("pk"):
            result[row.instrument_id] = Position(
                position_id=PositionId(row.position_id),
                instrument_id=InstrumentId(row.instrument_id),
                direction=Side(row.direction),
                quantity=row.quantity,
                average_entry_price=row.average_entry_price,
                realized_pnl=row.realized_pnl,
                unrealized_pnl=row.unrealized_pnl,
                opened_at=row.opened_at,
                status=PositionStatus(row.status),
                closed_at=row.closed_at,
            )
        return result

    def load_funds_for_reconciliation(self) -> Funds | None:
        row = PaperFundsRecord.objects.first()
        if row is None:
            return None
        return Funds(
            available_balance=row.available_balance,
            utilized_margin=row.utilized_margin,
            as_of=row.updated_at,
        )

    # ------------------------------------------------------------------
    # Checkpoint 43 Part 3/5: position-management lineage/exit-plan.
    # ------------------------------------------------------------------

    @transaction.atomic
    def attach_exit_plan(
        self,
        *,
        position_id: str,
        strategy_id: str,
        strategy_version: str,
        entry_order_id: str,
        exit_plan: ExitPlan,
        quantity: object,
        entry_price: object,
    ) -> None:
        """Called once, right after a position's entry order fills -
        never called again for the same position (a second call would
        silently reset `remaining_quantity`/`highest_favorable_price`,
        erasing genuine monitoring progress). The caller
        (`application/services/position_monitor_composition.py`) is
        responsible for calling this exactly once."""
        PaperPositionRecord.objects.filter(position_id=position_id).update(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            entry_order_id=entry_order_id,
            stop_loss=exit_plan.stop_loss,
            target_1=exit_plan.target_1,
            target_2=exit_plan.target_2,
            target_3=exit_plan.target_3,
            trailing_stop_distance=exit_plan.trailing_stop_distance,
            lifecycle_status=PositionLifecycleStatus.OPEN.value,
            remaining_quantity=quantity,
            highest_favorable_price=entry_price,
        )

    @transaction.atomic
    def update_position_lifecycle(
        self,
        *,
        position_id: str,
        lifecycle_status: PositionLifecycleStatus,
        remaining_quantity: object,
        highest_favorable_price: object,
        exit_reason: str,
    ) -> None:
        PaperPositionRecord.objects.filter(position_id=position_id).update(
            lifecycle_status=lifecycle_status.value,
            remaining_quantity=remaining_quantity,
            highest_favorable_price=highest_favorable_price,
            exit_reason=exit_reason,
        )

    def load_open_managed_positions(self) -> tuple[ManagedPosition, ...]:
        """Only positions that were given a REAL `ExitPlan` (via
        `attach_exit_plan()`) are returned as monitorable
        `ManagedPosition`s - a position with no strategy-declared exit
        rule (`stop_loss` and every target/trailing field all `None`)
        is honestly excluded, never given a fabricated plan just to be
        monitorable (Checkpoint 42's own "never fabricate a field"
        discipline, applied here)."""
        result: list[ManagedPosition] = []
        for row in PaperPositionRecord.objects.filter(status="OPEN"):
            has_any_rule = any(
                (
                    row.stop_loss,
                    row.target_1,
                    row.target_2,
                    row.target_3,
                    row.trailing_stop_distance,
                )
            )
            if not has_any_rule:
                continue
            position = Position(
                position_id=PositionId(row.position_id),
                instrument_id=InstrumentId(row.instrument_id),
                direction=Side(row.direction),
                quantity=row.quantity,
                average_entry_price=row.average_entry_price,
                realized_pnl=row.realized_pnl,
                unrealized_pnl=row.unrealized_pnl,
                opened_at=row.opened_at,
                status=PositionStatus(row.status),
                closed_at=row.closed_at,
            )
            exit_plan = ExitPlan(
                stop_loss=row.stop_loss,
                target_1=row.target_1,
                target_2=row.target_2,
                target_3=row.target_3,
                trailing_stop_distance=row.trailing_stop_distance,
            )
            remaining_quantity = (
                row.remaining_quantity if row.remaining_quantity is not None else row.quantity
            )
            if remaining_quantity <= 0:
                # Fully exited already (Decimal('0') is falsy in Python
                # but is a genuine, correct "nothing left" value - never
                # treated as "not set" and fallen back to the original
                # quantity, which would resurrect a closed position).
                continue
            highest_favorable_price = (
                row.highest_favorable_price
                if row.highest_favorable_price is not None
                else row.average_entry_price
            )
            result.append(
                ManagedPosition(
                    position=position,
                    strategy_id=row.strategy_id,  # type: ignore[arg-type]
                    strategy_version=row.strategy_version,
                    entry_order_id=OrderId(row.entry_order_id),
                    exit_plan=exit_plan,
                    lifecycle_status=PositionLifecycleStatus(row.lifecycle_status),
                    remaining_quantity=remaining_quantity,
                    highest_favorable_price=highest_favorable_price,
                )
            )
        return tuple(result)
