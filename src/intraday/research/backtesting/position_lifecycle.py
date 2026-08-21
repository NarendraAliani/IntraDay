# File: src/intraday/research/backtesting/position_lifecycle.py
#
# Checkpoint 64.29 Target 3: standalone, UNWIRED canonical Backtest
# Position lifecycle representation. Not wired into `engine.py`'s
# actual internal state (`OpenPosition`, `execution.py`) this
# checkpoint - `engine.py`'s own `OpenPosition` dataclass and bar-loop
# variables are left completely untouched, so existing numerical
# results cannot be affected by this module's existence.
#
# WHY A NEW MINIMAL ENUM, NOT A REUSE OF
# `domain.position_exit.contracts.PositionLifecycleStatus`: that enum's
# full vocabulary (OPEN, PARTIAL_EXIT, TARGET_1, TARGET_2, TARGET_3,
# TRAILING, STOPPED, CLOSED) is shaped for the PARTIAL-exit-capable
# Paper/live path (`evaluate_position_exit()`). The current backtest
# engine (`run_backtest()`, confirmed by direct code reading this
# checkpoint) is FULL-CLOSE-ONLY - it never populates PARTIAL_EXIT,
# TARGET_1/2/3, TRAILING, or STOPPED as intermediate states; a position
# is either still open or has been closed in a single atomic
# `_close_trade()` call. Reusing the six-member enum here would
# misrepresent the engine's real behavior (implying partial-exit
# progress states the backtest can never actually reach) - the
# checkpoint directive itself instructs "you may use a subset" but also
# "DO NOT go further than these 3 conceptual states." Since the real
# enum has no member matching the checkpoint's requested middle state
# name ("HELD" - "this position has been open across one or more bars
# with no exit yet, as distinct from the single bar it was opened on"),
# a literal subset-reuse is not possible without inventing a THIRD
# name inside someone else's enum. This module's own
# `BacktestPositionLifecycleStatus` is therefore a deliberately small,
# closed, 3-member vocabulary - not a parallel general-purpose lifecycle
# enum, and it is never used anywhere `PositionLifecycleStatus` already
# is (no import of this module by any Paper/live code path).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import ensure_utc
from intraday.research.backtesting import StrategyDirection

__all__ = [
    "BacktestPosition",
    "BacktestPositionLifecycleStatus",
    "close_backtest_position",
    "hold_backtest_position",
    "open_backtest_position",
]


class BacktestPositionLifecycleStatus(enum.Enum):
    """Exactly the three states Checkpoint 64.29 §6 specifies - no more,
    matching the current engine's real, full-close-only behavior."""

    OPEN = "OPEN"
    """Just entered - the bar loop has not yet advanced past the entry
    bar for this position."""
    HELD = "HELD"
    """Open and has survived at least one further bar without exiting -
    still full quantity, no partial exit ever populated (the current
    engine has none)."""
    CLOSED = "CLOSED"
    """Fully exited - terminal, matches `PositionLifecycleStatus.
    CLOSED`'s own `is_terminal()` convention in spirit, though this is a
    separate enum (see module docstring)."""


@dataclass(frozen=True, slots=True)
class BacktestPosition:
    """Canonical backtest-side position snapshot - fields named exactly
    per the checkpoint directive. Full-close-only by construction
    (Checkpoint 64.29 §6): `exited_quantity` is either `0` (OPEN/HELD)
    or the entire `original_quantity` (CLOSED) - there is no
    intermediate value, since the current engine never produces one."""

    position_id: str
    direction: StrategyDirection
    original_quantity: Decimal
    remaining_quantity: Decimal
    entry_price: Decimal
    entry_timestamp: datetime
    lifecycle_status: BacktestPositionLifecycleStatus

    def __post_init__(self) -> None:
        ensure_utc(self.entry_timestamp, field_name="BacktestPosition.entry_timestamp")
        if self.original_quantity <= 0:
            raise ValueError("BacktestPosition.original_quantity must be positive")
        if self.entry_price <= 0:
            raise ValueError("BacktestPosition.entry_price must be positive")
        if self.remaining_quantity < 0:
            raise ValueError("BacktestPosition.remaining_quantity must not be negative")
        if self.remaining_quantity > self.original_quantity:
            raise ValueError(
                "BacktestPosition.remaining_quantity must not exceed original_quantity"
            )
        # The invariant Checkpoint 64.29 §6 requires:
        #   original_quantity == exited_quantity + remaining_quantity
        # holds by construction (exited_quantity is DERIVED, never a
        # separately stored field that could drift), but the
        # state-specific full-close-only shape is enforced explicitly
        # below so a bug in a future caller is caught immediately
        # rather than silently producing an invalid intermediate state
        # this engine does not support today.
        if self.lifecycle_status in (
            BacktestPositionLifecycleStatus.OPEN,
            BacktestPositionLifecycleStatus.HELD,
        ):
            if self.exited_quantity != 0:
                raise ValueError(
                    "BacktestPosition: exited_quantity must be 0 while OPEN/HELD "
                    "(full-close-only engine - no partial exit exists today)"
                )
        elif (
            self.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED
            and self.exited_quantity != self.original_quantity
        ):
            raise ValueError(
                "BacktestPosition: exited_quantity must equal original_quantity "
                "when CLOSED (full-close-only engine)"
            )

    @property
    def exited_quantity(self) -> Decimal:
        return self.original_quantity - self.remaining_quantity


def open_backtest_position(
    *,
    position_id: str,
    direction: StrategyDirection,
    quantity: Decimal,
    entry_price: Decimal,
    entry_timestamp: datetime,
) -> BacktestPosition:
    """The only way a `BacktestPosition` is created - always starts
    OPEN, full quantity remaining, matching `engine.py`'s own entry
    branch (a position is always entered at its full sized quantity,
    never partially)."""
    return BacktestPosition(
        position_id=position_id,
        direction=direction,
        original_quantity=quantity,
        remaining_quantity=quantity,
        entry_price=entry_price,
        entry_timestamp=entry_timestamp,
        lifecycle_status=BacktestPositionLifecycleStatus.OPEN,
    )


def hold_backtest_position(position: BacktestPosition) -> BacktestPosition:
    """OPEN -> HELD transition only (a no-op, still OPEN->HELD, if
    called again on an already-HELD position - idempotent, never
    raises). Quantity is untouched - the current engine has no
    quantity-affecting event between entry and exit."""
    if position.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED:
        raise ValueError("cannot transition a CLOSED BacktestPosition to HELD")
    if position.lifecycle_status is BacktestPositionLifecycleStatus.HELD:
        return position
    return BacktestPosition(
        position_id=position.position_id,
        direction=position.direction,
        original_quantity=position.original_quantity,
        remaining_quantity=position.remaining_quantity,
        entry_price=position.entry_price,
        entry_timestamp=position.entry_timestamp,
        lifecycle_status=BacktestPositionLifecycleStatus.HELD,
    )


def close_backtest_position(position: BacktestPosition) -> BacktestPosition:
    """OPEN/HELD -> CLOSED, full-close-only (Checkpoint 64.29 §6): the
    ENTIRE remaining quantity is exited in one step, matching
    `engine.py`'s own `_close_trade()`, which always closes
    `open_position.quantity` in full, never a partial amount."""
    if position.lifecycle_status is BacktestPositionLifecycleStatus.CLOSED:
        raise ValueError("BacktestPosition is already CLOSED")
    return BacktestPosition(
        position_id=position.position_id,
        direction=position.direction,
        original_quantity=position.original_quantity,
        remaining_quantity=Decimal("0"),
        entry_price=position.entry_price,
        entry_timestamp=position.entry_timestamp,
        lifecycle_status=BacktestPositionLifecycleStatus.CLOSED,
    )
