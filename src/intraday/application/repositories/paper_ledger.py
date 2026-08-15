# File: src/intraday/application/repositories/paper_ledger.py
#
# Checkpoint 35 Part 3: the paper-ledger persistence Protocol - mirrors
# every other `application/repositories/*.py` Protocol-here/Django-
# implementation-in-infrastructure split already established in this
# project (`kill_switch.py`, `provider_settings.py`).
from __future__ import annotations

from typing import Protocol

from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.order.events import OrderEvent
from intraday.domain.position.contracts import Position
from intraday.domain.trade.contracts import Trade


class PaperLedgerRepository(Protocol):
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
    ) -> None: ...
