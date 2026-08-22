# File: src/intraday/domain/position/contracts.py
#
# Canonical intraday Position contract (Checkpoint 5) — actual
# broker/account EXPOSURE at a point in time (Checkpoint 2 §5), distinct
# from Order (a request) and Trade (a completed round trip). Intraday
# only: no carried-forward/overnight state exists in this contract
# (Rule 5.4). No P&L calculation or square-off logic is implemented here
# (Checkpoint 5 Section 16).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, PositionId, Side, ensure_utc


class PositionStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class Position:
    """A position is a VALUE SNAPSHOT, not a running calculator.
    `realized_pnl`/`unrealized_pnl` are populated by
    `trading_engine/position_lifecycle` (a later checkpoint) — this
    dataclass performs no P&L arithmetic itself."""

    position_id: PositionId
    instrument_id: InstrumentId
    direction: Side
    quantity: Decimal
    average_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime
    status: PositionStatus
    closed_at: datetime | None = None
    realized_net_pnl: Decimal | None = None
    """Checkpoint 64.37: ADDITIVE ONLY — never redefines `realized_pnl`
    above, which keeps its existing, unchanged, cost-exclusive/gross
    meaning for every existing consumer. `realized_net_pnl`, when
    populated by a producer that tracks attributable transaction costs
    (e.g. `PaperBroker`), is `realized_pnl` minus attributable
    transaction costs — see `domain.trade.net_pnl.compute_realized_net_pnl`
    for the exact formula. `None` when a producer does not populate it
    (e.g. any pre-64.37 construction site), so this field is fully
    backward compatible: no existing caller is required to supply it."""

    def __post_init__(self) -> None:
        ensure_utc(self.opened_at, field_name="Position.opened_at")
        if self.closed_at is not None:
            ensure_utc(self.closed_at, field_name="Position.closed_at")
            if self.closed_at < self.opened_at:
                raise ValueError("Position.closed_at must not be before opened_at")
        if self.quantity <= 0:
            raise ValueError("Position.quantity must be positive")
        if self.average_entry_price <= 0:
            raise ValueError("Position.average_entry_price must be positive")
        if self.status is PositionStatus.CLOSED and self.closed_at is None:
            raise ValueError("Position.closed_at is required when status is CLOSED")
        if self.status is PositionStatus.OPEN and self.closed_at is not None:
            raise ValueError("Position.closed_at must be None when status is OPEN")
