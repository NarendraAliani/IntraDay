# File: src/intraday/domain/trade/contracts.py
#
# Canonical Trade contract (Checkpoint 5) — a COMPLETED, CLOSED execution
# outcome (Checkpoint 2 §5 addition), the settled fact of what actually
# happened. Links Signal -> Strategy -> Order(s) -> Position so the
# platform can separately answer "was the strategy wrong?"
# (signal_intelligence/signal_verification, comparing a Signal against its
# theoretical outcome) and "was execution poor?" (comparing THIS Trade's
# realized figures against the originating Order's intent) — never both
# from the same object. No trade-calculation logic is implemented here
# (Checkpoint 5 Section 17).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    PositionId,
    Side,
    SignalId,
    StrategyId,
    TradeId,
    ensure_utc,
)


@dataclass(frozen=True, slots=True)
class Trade:
    """A closed round-trip: entry + exit, on one instrument, for one
    strategy. `order_ids` may contain more than one order (e.g. entry and
    exit legs, or partial fills consolidated by `execution_management` in
    a later checkpoint) — this contract only records the linkage, not how
    the consolidation happened.
    """

    trade_id: TradeId
    strategy_id: StrategyId
    instrument_id: InstrumentId
    direction: Side
    order_ids: tuple[OrderId, ...]
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    opened_at: datetime
    closed_at: datetime
    signal_id: SignalId | None = None
    position_id: PositionId | None = None
    realized_net_pnl: Decimal | None = None
    """Checkpoint 64.37: ADDITIVE ONLY — never redefines `realized_pnl`
    above, which keeps its existing, unchanged, cost-exclusive/gross
    meaning for every existing consumer. `realized_net_pnl`, when
    populated by a producer that tracks attributable transaction costs
    (e.g. `PaperBroker`), is `realized_pnl` minus this trade's
    attributable transaction cost — see
    `domain.trade.net_pnl.compute_realized_net_pnl`. `None` when a
    producer does not populate it, so this field is fully backward
    compatible."""

    def __post_init__(self) -> None:
        ensure_utc(self.opened_at, field_name="Trade.opened_at")
        ensure_utc(self.closed_at, field_name="Trade.closed_at")
        if self.closed_at < self.opened_at:
            raise ValueError("Trade.closed_at must not be before opened_at")
        if not self.order_ids:
            raise ValueError("Trade.order_ids must reference at least one order")
        if self.entry_price <= 0 or self.exit_price <= 0:
            raise ValueError("Trade.entry_price and exit_price must both be positive")
        if self.quantity <= 0:
            raise ValueError("Trade.quantity must be positive")
