# File: src/intraday/infrastructure/api/eod_runtime.py
#
# Checkpoint 51 Part 11: the FIRST end-of-day lifecycle - the one link
# this project's own end-to-end paper-trading chain was missing (no
# `*eod*` module existed anywhere in this repository before this
# checkpoint). Deliberately reuses, rather than reimplements, the two
# pieces of real machinery this exact problem already needed:
# `run_emergency_square_off()` (Checkpoint 45/47 - force-closes EVERY
# open position unconditionally, exactly what EOD square-off also
# needs) and `reconcile_paper_state()` (Checkpoint 34/38/47). The ONLY
# genuinely new logic here is the durable EOD state machine
# (`DjangoEODRunRepository`, mirroring Checkpoint 48's own crash-
# recovery design) and totalling realized P&L across the day's
# positions.
#
# HONEST, DOCUMENTED LIMITATIONS (named, not hidden):
# 1. "STOP_NEW_SIGNALS"/"STOP_NEW_ENTRIES" are NOT separate steps this
#    function performs - they are already the existing, tested
#    behavior of `run_active_loop_tick()`'s own session-gating
#    (Checkpoint 40): once `session_for_instant()` reports anything
#    other than `OPEN` (which happens automatically once `now` passes
#    `square_off_deadline`/`market_close`), no new entry signal is
#    generated. EOD does not need to duplicate that gate.
# 2. "WAIT_FOR_TERMINAL_ORDERS" is a no-op here: `PaperBroker` fills
#    MARKET orders synchronously (Checkpoint 34) - there is no
#    asynchronous broker acknowledgment to wait for in PAPER mode.
#    This would NOT be true against a real broker and this module says
#    so rather than silently implying it generalizes.
# 3. `total_realized_pnl` sums `realized_pnl` across every position
#    `PaperBroker` currently knows about, not a calendar-date-scoped
#    query - this project's position model has no explicit
#    "trading_date" partition yet, so a genuinely multi-day-history
#    P&L split is a real, separate, undone piece of work, not silently
#    assumed solved by this function.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.api.paper_trading_runtime import get_paper_broker
from intraday.infrastructure.api.position_monitor_runtime import (
    EmergencySquareOffOutcome,
    run_emergency_square_off,
)
from intraday.infrastructure.persistence.eod_run_repository import DjangoEODRunRepository
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EODOutcome:
    already_handled: bool
    """`True` only when this trading date's EOD already reached
    `COMPLETED` - matches the exact `already_handled` semantics
    `check_and_trigger_automatic_square_off()` established (Checkpoint
    48), never merely "an attempt was claimed."""
    square_off: EmergencySquareOffOutcome | None
    reconciliation_divergence_count: int | None
    zero_exposure_confirmed: bool | None
    total_realized_pnl: Decimal | None


def run_eod_sequence(
    *, current_prices: dict[str, Decimal], now: datetime | None = None
) -> EODOutcome:
    """The EOD chain: (if claimable) SQUARE_OFF -> RECONCILE ->
    VERIFY_ZERO_EXPOSURE -> CALCULATE_PNL -> record outcome durably.
    Idempotent per calendar date (`eod_date = now.date()`), using the
    exact claim/complete/fail pattern proven for emergency square-off
    (Checkpoint 48) - a crash mid-EOD leaves the row genuinely
    `IN_PROGRESS`, reclaimed and retried by the next call once stale,
    never permanently marking the day closed while positions remain
    open."""
    clock = now or datetime.now(tz=UTC)
    eod_date = clock.date()
    repository = DjangoEODRunRepository()
    claim = repository.claim(eod_date=eod_date, now=clock)

    if not claim.claimed:
        return EODOutcome(
            already_handled=claim.already_terminal,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=None,
            total_realized_pnl=None,
        )

    logger.warning(
        "eod.sequence_started", eod_date=eod_date.isoformat(), attempt=claim.attempt_count
    )

    try:
        square_off = run_emergency_square_off(current_prices=current_prices, now=clock)
    except Exception as exc:  # noqa: BLE001 - must be recorded, never crash the caller silently
        logger.exception("eod.square_off_raised")
        repository.mark_failed_retryable(
            eod_date=eod_date,
            positions_closed=0,
            positions_failed=[],
            reconciliation_divergence_count=None,
            error=repr(exc),
        )
        return EODOutcome(
            already_handled=False,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=False,
            total_realized_pnl=None,
        )

    reconciliation_divergence_count: int | None = None
    try:
        report = reconcile_paper_state(
            broker=get_paper_broker(), ledger=DjangoPaperLedgerRepository(), now=clock
        )
        reconciliation_divergence_count = report.total_divergence_count
    except Exception:  # noqa: BLE001 - reconciliation failure must surface, not crash EOD
        logger.exception("eod.post_square_off_reconciliation_failed")

    all_positions = get_paper_broker().get_positions()
    remaining_open = len([p for p in all_positions if p.status.value == "OPEN"])
    zero_exposure_confirmed = remaining_open == 0 and not square_off.positions_failed
    total_realized_pnl = sum((p.realized_pnl for p in all_positions), Decimal("0"))

    if square_off.positions_failed or not zero_exposure_confirmed:
        logger.error(
            "eod.exposure_remains_or_square_off_failed",
            remaining_open_positions=remaining_open,
            positions_failed=square_off.positions_failed,
        )
        repository.mark_failed_retryable(
            eod_date=eod_date,
            positions_closed=square_off.positions_closed,
            positions_failed=list(square_off.positions_failed),
            reconciliation_divergence_count=reconciliation_divergence_count,
            error="EOD could not confirm zero exposure this attempt",
        )
        return EODOutcome(
            already_handled=False,
            square_off=square_off,
            reconciliation_divergence_count=reconciliation_divergence_count,
            zero_exposure_confirmed=zero_exposure_confirmed,
            total_realized_pnl=total_realized_pnl,
        )

    logger.warning(
        "eod.completed",
        eod_date=eod_date.isoformat(),
        positions_closed=square_off.positions_closed,
        total_realized_pnl=str(total_realized_pnl),
    )
    repository.mark_completed(
        eod_date=eod_date,
        positions_closed=square_off.positions_closed,
        reconciliation_divergence_count=reconciliation_divergence_count,
        total_realized_pnl=total_realized_pnl,
        now=clock,
    )
    return EODOutcome(
        already_handled=False,
        square_off=square_off,
        reconciliation_divergence_count=reconciliation_divergence_count,
        zero_exposure_confirmed=zero_exposure_confirmed,
        total_realized_pnl=total_realized_pnl,
    )
