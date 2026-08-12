# File: src/intraday/domain/signal/contracts.py
#
# Canonical Signal contract (Checkpoint 5) — a research/trading decision
# CANDIDATE only. Deliberately excludes anything resembling an Order or
# Position (Checkpoint 2 §5 Signal/Order/Position/Trade separation) — no
# broker-facing or execution field exists here.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    Side,
    SignalId,
    StrategyId,
    Timeframe,
    Version,
    ensure_utc,
)


class SignalStatus(enum.Enum):
    """Signal lifecycle state. `signal_intelligence/signal_lifecycle` owns
    the transition RULES in a later checkpoint; this enum only names the
    valid states."""

    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"  # became an Order


@dataclass(frozen=True, slots=True)
class Signal:
    """A candidate trading decision produced by signal_intelligence.

    Answers "what might we do?" — never "what did we do?" (that's Order's
    and Trade's job respectively). `theoretical_entry`/`theoretical_stop_loss`/
    `theoretical_targets` are levels a strategy PROPOSES, not broker-facing
    order parameters — see `domain.order.OrderIntent` for the risk-approved
    execution request this may eventually become.
    """

    signal_id: SignalId
    strategy_id: StrategyId
    strategy_version: Version
    instrument_id: InstrumentId
    generated_at: datetime
    timeframe: Timeframe
    direction: Side
    theoretical_entry: Decimal
    theoretical_stop_loss: Decimal
    theoretical_targets: tuple[Decimal, ...]
    feature_snapshot_version: Version
    status: SignalStatus = SignalStatus.PENDING
    confidence: Decimal | None = None  # within [0, 1] where provided
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        ensure_utc(self.generated_at, field_name="Signal.generated_at")
        if self.expires_at is not None:
            ensure_utc(self.expires_at, field_name="Signal.expires_at")
            if self.expires_at <= self.generated_at:
                raise ValueError("Signal.expires_at must be after generated_at")
        if self.theoretical_entry <= 0:
            raise ValueError("Signal.theoretical_entry must be positive")
        if self.theoretical_stop_loss <= 0:
            raise ValueError("Signal.theoretical_stop_loss must be positive")
        if self.confidence is not None and not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ValueError("Signal.confidence must be within [0, 1]")
        if self.direction is Side.BUY and self.theoretical_stop_loss >= self.theoretical_entry:
            raise ValueError(
                "For a BUY signal, theoretical_stop_loss must be below theoretical_entry"
            )
        if self.direction is Side.SELL and self.theoretical_stop_loss <= self.theoretical_entry:
            raise ValueError(
                "For a SELL signal, theoretical_stop_loss must be above theoretical_entry"
            )
        for target in self.theoretical_targets:
            if target <= 0:
                raise ValueError("Signal.theoretical_targets values must all be positive")
