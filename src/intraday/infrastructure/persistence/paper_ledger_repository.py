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
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.order.events import OrderEvent
from intraday.domain.position.contracts import Position
from intraday.domain.shared_kernel.contracts import OrderId
from intraday.domain.trade.contracts import Trade
from intraday.infrastructure.persistence.models import (
    PaperFundsRecord,
    PaperOrderRecord,
    PaperPositionRecord,
    PaperTradeRecord,
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
