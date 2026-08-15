# File: src/intraday/infrastructure/api/paper_reconciliation_runtime.py
#
# Checkpoint 38 Part 13: "build paper-mode reconciliation first," using
# the EXISTING broker-neutral reconciliation engine
# (control_plane.reconciliation, Checkpoint 34 Part 13/Decision 152)
# verbatim - never a second, parallel reconciliation architecture. Only
# the SOURCE of "broker" data differs between paper and a future Dhan
# adapter (both structurally satisfy `domain.broker.BrokerGateway`,
# Decision 149) - `reconcile_paper_state()` calls the SAME
# `reconcile_*()`/`build_reconciliation_report()` functions a future
# Dhan reconciliation composition would call, with `DhanBroker.
# get_orders()`/etc. supplying the broker side instead of `PaperBroker`.
#
# Lives in `infrastructure/api/`, NOT `application/services/` -
# mirrors `paper_trading_runtime.py`'s own precedent (Decision 153):
# this module composes concrete infrastructure (`PaperBroker`,
# `DjangoPaperLedgerRepository`) and would break `.importlinter`
# contract 6 ("application must not depend on infrastructure") if
# placed in `application/services/` instead.
from __future__ import annotations

from datetime import datetime

from intraday.control_plane.reconciliation.contracts import ReconciliationReport
from intraday.control_plane.reconciliation.reconciler import (
    build_reconciliation_report,
    reconcile_funds,
    reconcile_orders,
    reconcile_positions,
    reconcile_trades,
)
from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.position.contracts import Position
from intraday.domain.shared_kernel.contracts import OrderId, TradeId
from intraday.domain.trade.contracts import Trade
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)


def reconcile_paper_state(
    *,
    broker: PaperBroker,
    ledger: DjangoPaperLedgerRepository,
    now: datetime,
) -> ReconciliationReport:
    """The "expected local state" is the DURABLE ledger (`PaperOrderRecord`/
    etc. - what `PaperTradingService._persist()` wrote after every
    mutation, Checkpoint 35); the "broker state" is `PaperBroker`'s own
    current in-memory truth (Decision 146: the broker is always the
    authoritative source). Divergence between them means a sync
    failed, was skipped, or the process restarted with a broker that
    reset its in-memory state while the ledger retained stale rows -
    exactly the class of bug this checkpoint's reconciliation loop
    exists to surface. DETECT AND CLASSIFY ONLY (Decision 152 - no
    corrective action)."""
    local_order_statuses: dict[OrderId, OrderStatus] = (
        ledger.load_order_statuses_for_reconciliation()
    )
    broker_orders: tuple[BrokerOrderStatusReport, ...] = broker.get_orders()

    local_trades: dict[TradeId, Trade] = ledger.load_trades_for_reconciliation()
    broker_trades: tuple[Trade, ...] = broker.get_trades()

    local_positions: dict[str, Position] = ledger.load_positions_for_reconciliation()
    broker_positions: tuple[Position, ...] = broker.get_positions()

    local_funds = ledger.load_funds_for_reconciliation()
    broker_funds: Funds = broker.get_funds()

    order_divergences = reconcile_orders(local=local_order_statuses, broker=broker_orders, now=now)
    trade_divergences = reconcile_trades(local=local_trades, broker=broker_trades, now=now)
    position_divergences = reconcile_positions(
        local=local_positions, broker=broker_positions, now=now
    )
    funds_divergences = (
        reconcile_funds(local=local_funds, broker=broker_funds, now=now)
        if local_funds is not None
        else ()
    )

    return build_reconciliation_report(
        order_divergences=order_divergences,
        trade_divergences=trade_divergences,
        position_divergences=position_divergences,
        funds_divergences=funds_divergences,
        now=now,
    )
