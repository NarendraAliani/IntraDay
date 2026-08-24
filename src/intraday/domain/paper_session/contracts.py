# File: src/intraday/domain/paper_session/contracts.py
#
# Checkpoint 64.68 §14: the PAPER TRADING SESSION state machine.
#
# WHY A NEW ENUM RATHER THAN REUSING `LivePaperSessionState`:
# `application/services/live_paper_session.py` (Checkpoint 64.13)
# already models a DIFFERENT question - "what state is the operator's
# LIVE scanner-worker session in" (NOT_READY/READY/STARTING/RUNNING/
# STOPPING/STOPPED/FAILED), whose STARTING/STOPPING states exist
# entirely because a separate OS worker process reconciles
# asynchronously. A deterministic REPLAY session has no asynchronous
# reconciliation and no live readiness gate: its state advances
# synchronously, inside the request that asks for it. Folding the two
# vocabularies together would force one of them to carry states that
# can never occur, so Checkpoint 64.68's own explicitly-specified
# five-state vocabulary (STOPPED/RUNNING/PAUSED/COMPLETED/FAILED) is
# modelled separately and honestly. `LivePaperSessionState` is left
# COMPLETELY untouched by this checkpoint.
#
# This module is PURE: no I/O, no Django, no clock, no randomness -
# exactly like `domain/order/state_machine.py`, which it is modelled on.
from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal


class PaperSessionStatus(enum.Enum):
    """Checkpoint 64.68 §14's five states, verbatim."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaperSessionCommand(enum.Enum):
    """The operator-or-engine-initiated transitions. START/PAUSE/RESUME/
    STOP/RESET are operator commands; COMPLETE/FAIL are engine outcomes
    (the replay ran out of bars, or the replay raised)."""

    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    RESET = "RESET"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"


class InvalidPaperSessionTransitionError(ValueError):
    """Raised by `apply_command()` for a transition that is NOT in the
    table below. Never raised for an idempotent no-op the caller has
    already classified via `is_idempotent_no_op()` - see
    `application/services/replay_paper_session.py`, which answers a
    double-START/double-STOP with a refusal result, not an exception."""


_TRANSITIONS: dict[tuple[PaperSessionStatus, PaperSessionCommand], PaperSessionStatus] = {
    # §14's explicitly listed valid transitions.
    (PaperSessionStatus.STOPPED, PaperSessionCommand.START): PaperSessionStatus.RUNNING,
    (PaperSessionStatus.RUNNING, PaperSessionCommand.PAUSE): PaperSessionStatus.PAUSED,
    (PaperSessionStatus.PAUSED, PaperSessionCommand.RESUME): PaperSessionStatus.RUNNING,
    (PaperSessionStatus.RUNNING, PaperSessionCommand.STOP): PaperSessionStatus.STOPPED,
    (PaperSessionStatus.PAUSED, PaperSessionCommand.STOP): PaperSessionStatus.STOPPED,
    # Engine outcomes - reachable only from an actively-advancing session.
    (PaperSessionStatus.RUNNING, PaperSessionCommand.COMPLETE): PaperSessionStatus.COMPLETED,
    (PaperSessionStatus.RUNNING, PaperSessionCommand.FAIL): PaperSessionStatus.FAILED,
    (PaperSessionStatus.PAUSED, PaperSessionCommand.FAIL): PaperSessionStatus.FAILED,
    # RESET returns a session to a fresh STOPPED session with a zeroed
    # replay cursor - permitted ONLY from a non-advancing state. See
    # `RESET_WHILE_RUNNING_SEMANTICS` below.
    (PaperSessionStatus.STOPPED, PaperSessionCommand.RESET): PaperSessionStatus.STOPPED,
    (PaperSessionStatus.COMPLETED, PaperSessionCommand.RESET): PaperSessionStatus.STOPPED,
    (PaperSessionStatus.FAILED, PaperSessionCommand.RESET): PaperSessionStatus.STOPPED,
    # A COMPLETED or FAILED session may also be re-STARTed after a RESET
    # only - never directly, so a finished session's results can never be
    # silently appended to.
}

RESET_WHILE_RUNNING_SEMANTICS = (
    "RESET is EXPLICITLY REJECTED while a session is RUNNING or PAUSED. The session must be "
    "STOPPED first. This is the documented choice required by Checkpoint 64.68 §15: silently "
    "discarding an in-flight session's positions and P&L on an accidental RESET click would be "
    "the more dangerous of the two available semantics."
)

_IDEMPOTENT_NO_OPS: frozenset[tuple[PaperSessionStatus, PaperSessionCommand]] = frozenset(
    {
        # Double-START: the session is already advancing. Refused as a
        # no-op, NEVER a second session (§15).
        (PaperSessionStatus.RUNNING, PaperSessionCommand.START),
        (PaperSessionStatus.PAUSED, PaperSessionCommand.START),
        # Double-STOP: already stopped/finished. Refused as a no-op, and
        # critically it never mutates the persisted cursor or results
        # (§15's "stopping twice does not corrupt state").
        (PaperSessionStatus.STOPPED, PaperSessionCommand.STOP),
        (PaperSessionStatus.COMPLETED, PaperSessionCommand.STOP),
        (PaperSessionStatus.FAILED, PaperSessionCommand.STOP),
        # Double-PAUSE / double-RESUME.
        (PaperSessionStatus.PAUSED, PaperSessionCommand.PAUSE),
        (PaperSessionStatus.RUNNING, PaperSessionCommand.RESUME),
    }
)


def is_valid_command(status: PaperSessionStatus, command: PaperSessionCommand) -> bool:
    return (status, command) in _TRANSITIONS


def is_idempotent_no_op(status: PaperSessionStatus, command: PaperSessionCommand) -> bool:
    """`True` for a repeated command whose intent is ALREADY satisfied -
    the caller should refuse it without error and without mutating any
    state. Distinct from a genuinely INVALID transition (e.g. RESUME
    from STOPPED, RESET while RUNNING), which raises."""
    return (status, command) in _IDEMPOTENT_NO_OPS


def apply_command(status: PaperSessionStatus, command: PaperSessionCommand) -> PaperSessionStatus:
    """Pure. Returns the NEW status, or raises
    `InvalidPaperSessionTransitionError` for anything not in the
    transition table - including every idempotent no-op, which callers
    are expected to screen with `is_idempotent_no_op()` first."""
    try:
        return _TRANSITIONS[(status, command)]
    except KeyError as exc:
        detail = ""
        if command is PaperSessionCommand.RESET:
            detail = f" {RESET_WHILE_RUNNING_SEMANTICS}"
        raise InvalidPaperSessionTransitionError(
            f"{command.value} is not a valid command for a {status.value} paper session.{detail}"
        ) from exc


@dataclass(frozen=True, slots=True)
class PaperAccountSnapshot:
    """Checkpoint 64.68 §3: the paper ACCOUNT, as a value object.

    CRITICAL - THIS IS NOT A SECOND P&L CALCULATOR (§16). Every monetary
    field here is COPIED from a figure the existing canonical accounting
    already produced (`PaperBroker.get_funds()`, `.get_equity()`,
    `.get_total_unrealized_pnl()`, and `Position.realized_net_pnl`,
    which `domain/trade/net_pnl.compute_realized_net_pnl` produced).
    The ONLY arithmetic this dataclass performs is `total_pnl`
    (realized + unrealized) and `drawdown` (peak_equity - equity),
    neither of which exists anywhere else in the codebase to duplicate.
    """

    starting_capital: Decimal
    available_capital: Decimal
    """`PaperBroker.get_funds().available_balance` verbatim."""
    utilized_margin: Decimal
    """`PaperBroker.get_funds().utilized_margin` verbatim."""
    realized_pnl: Decimal
    """Sum of `Position.realized_net_pnl` - the COST-INCLUSIVE figure,
    the same semantic quantity the Risk Gate is already fed by
    `PaperTradingService.submit_order()` (Checkpoint 64.37). Never the
    cost-exclusive `Position.realized_pnl`."""
    unrealized_pnl: Decimal
    """`PaperBroker.get_total_unrealized_pnl()` verbatim."""
    equity: Decimal
    """`PaperBroker.get_equity()` verbatim (cash + signed market value of
    open positions) - never independently re-derived here."""
    peak_equity: Decimal
    """The running maximum of `equity` observed across the replay's own
    equity curve, seeded at `starting_capital`."""

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def drawdown(self) -> Decimal:
        """Peak-to-current equity drawdown, never negative."""
        fall = self.peak_equity - self.equity
        return fall if fall > 0 else Decimal("0")


__all__ = [
    "RESET_WHILE_RUNNING_SEMANTICS",
    "InvalidPaperSessionTransitionError",
    "PaperAccountSnapshot",
    "PaperSessionCommand",
    "PaperSessionStatus",
    "apply_command",
    "is_idempotent_no_op",
    "is_valid_command",
]
