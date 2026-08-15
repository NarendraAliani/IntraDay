# File: src/intraday/trading_engine/position_management/contracts.py
#
# Checkpoint 42 Part 3-4: the position lifecycle and strategy exit
# contracts. `ExitPlan` is the "Strategy Exit Contract" Part 4 requires
# - a strategy that cannot supply one is HONESTLY represented by
# `ExitPlan=None` on a `ManagedPosition`, never a fabricated stop-loss/
# target (the same "never fabricate a field" discipline the signal
# communication engine already established, Checkpoint 37/38).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.position.contracts import Position
from intraday.domain.shared_kernel.contracts import OrderId, StrategyId, ensure_utc


class ExitReason(enum.Enum):
    """Exhaustive, closed vocabulary (mirrors `RiskRejectionReason`'s
    own "one member per required control, nothing else" discipline,
    Checkpoint 34) - every exit decision cites exactly one."""

    STOP_LOSS = "STOP_LOSS"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_EXIT = "TIME_EXIT"
    SESSION_SQUARE_OFF = "SESSION_SQUARE_OFF"
    MANUAL_EXIT = "MANUAL_EXIT"
    RISK_HALT = "RISK_HALT"


class PositionLifecycleStatus(enum.Enum):
    """Checkpoint 42 Part 3's required deterministic lifecycle -
    strictly ordered by how far a position has progressed toward full
    exit. `PARTIAL_EXIT` is a distinct state from `TARGET_1`/etc.
    themselves (Part 12's "PARTIAL_EXIT" state) because a position can
    be partially exited at ANY target, not only the first."""

    OPEN = "OPEN"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    TRAILING = "TRAILING"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"

    def is_terminal(self) -> bool:
        return self is PositionLifecycleStatus.CLOSED


# The order lifecycle progresses through in strict sequence - used to
# make "has this position already passed target N" a simple index
# comparison rather than ad hoc conditionals scattered through the
# monitor.
_LIFECYCLE_ORDER: tuple[PositionLifecycleStatus, ...] = (
    PositionLifecycleStatus.OPEN,
    PositionLifecycleStatus.TARGET_1,
    PositionLifecycleStatus.TARGET_2,
    PositionLifecycleStatus.TARGET_3,
    PositionLifecycleStatus.CLOSED,
)


@dataclass(frozen=True, slots=True)
class ExitPlan:
    """Checkpoint 42 Part 4's "Strategy Exit Contract" - what a
    production-eligible strategy DECLARES at signal time. Every field
    beyond `stop_loss` is optional because not every strategy computes
    every level (Checkpoint 36's own established honesty about
    `ema_crossover` specifically) - `None` is a genuine "this strategy
    does not define this," never a placeholder."""

    stop_loss: Decimal | None
    target_1: Decimal | None = None
    target_2: Decimal | None = None
    target_3: Decimal | None = None
    trailing_stop_distance: Decimal | None = None
    """Distance (in price, not percent) the trailing stop trails behind
    the best price reached since entry - `None` means no trailing
    behavior is defined."""
    max_holding_period_minutes: int | None = None

    def has_any_exit_rule(self) -> bool:
        return any(
            (
                self.stop_loss,
                self.target_1,
                self.target_2,
                self.target_3,
                self.trailing_stop_distance,
                self.max_holding_period_minutes,
            )
        )


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    """Checkpoint 42 Part 3's full position record - wraps the
    canonical `domain.position.Position` (never replaces it; every
    field that contract already owns stays there) with the additional
    lineage/exit-tracking fields a PAPER trading loop actually needs to
    monitor a position, none of which belong on the broker-neutral
    domain snapshot itself."""

    position: Position
    strategy_id: StrategyId
    strategy_version: str
    entry_order_id: OrderId
    exit_plan: ExitPlan | None
    """`None` when the originating strategy provides no exit rules at
    all (Checkpoint 36's `ema_crossover`, today) - the position exists
    and is tracked, but `evaluate_position_exit()` will never generate
    an automatic exit decision for it; see that function's own
    docstring."""
    lifecycle_status: PositionLifecycleStatus
    remaining_quantity: Decimal
    highest_favorable_price: Decimal
    """The best price seen since entry, in the position's favor (higher
    for a long, lower for a short) - the input the trailing-stop rule
    needs; updated every time the monitor observes a new price, even
    when no exit fires."""
    exit_reason: ExitReason | None = None

    def __post_init__(self) -> None:
        if self.remaining_quantity < 0:
            raise ValueError("ManagedPosition.remaining_quantity must not be negative")
        if self.remaining_quantity > self.position.quantity:
            raise ValueError(
                "ManagedPosition.remaining_quantity must not exceed the position's own quantity"
            )

    def has_passed(self, status: PositionLifecycleStatus) -> bool:
        """Whether the lifecycle has already reached or passed
        `status` - e.g. `has_passed(TARGET_1)` is True once the
        position is at `TARGET_2`, `TARGET_3`, or `CLOSED`."""
        if self.lifecycle_status not in _LIFECYCLE_ORDER or status not in _LIFECYCLE_ORDER:
            return False
        return _LIFECYCLE_ORDER.index(self.lifecycle_status) >= _LIFECYCLE_ORDER.index(status)


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """What `evaluate_position_exit()` returns when a real exit
    condition fires - the position layer's own auditable record of
    WHY, handed to the risk/paper-execution layer to actually act on
    (Part 4's explicit "the broker executes orders... the strategy/
    risk/position layer determines WHY")."""

    position_id: str
    reason: ExitReason
    exit_price: Decimal
    exit_quantity: Decimal
    new_lifecycle_status: PositionLifecycleStatus
    decided_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.decided_at, field_name="ExitDecision.decided_at")
        if self.exit_quantity <= 0:
            raise ValueError("ExitDecision.exit_quantity must be positive")
