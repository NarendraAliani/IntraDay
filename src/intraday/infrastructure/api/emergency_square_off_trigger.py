# File: src/intraday/infrastructure/api/emergency_square_off_trigger.py
#
# Checkpoint 46 Part 2: closes THE named P0 gap from Checkpoint 45's
# own register - `run_emergency_square_off()` existed and was tested,
# but nothing automatically invoked it when the kill switch engaged.
# This module is that automatic trigger.
#
# Checkpoint 48 Part 3 REPLACES the original cache-only idempotency
# (`cache.add()`, 24h TTL) with the durable
# `DjangoEmergencySquareOffEventRepository` state machine. The bug in
# the old design, named honestly in Checkpoint 47's own report and NOT
# allowed to disappear into Checkpoint 48: `cache.add()` marked a halt
# event "handled" the INSTANT it was claimed, not when square-off
# actually finished - a crash between claim and completion left the
# event permanently "handled" with positions possibly still open, and
# nothing would ever retry it. The new design claims IN_PROGRESS
# first, and only reaches COMPLETED after square-off ran AND
# reconciliation confirmed zero exposure - see
# `emergency_square_off_event_repository.py`'s module docstring for
# the full state machine and its crash-recovery mechanism.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from intraday.application.services.kill_switch import KillSwitchService
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.api.paper_trading_runtime import get_paper_broker
from intraday.infrastructure.api.position_monitor_runtime import (
    EmergencySquareOffOutcome,
    run_emergency_square_off,
)
from intraday.infrastructure.persistence.emergency_square_off_event_repository import (
    DjangoEmergencySquareOffEventRepository,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AutomaticSquareOffCheckOutcome:
    kill_switch_engaged: bool
    already_handled: bool
    square_off: EmergencySquareOffOutcome | None
    reconciliation_divergence_count: int | None
    zero_exposure_confirmed: bool | None
    """`None` when square-off did not run this check; `True`/`False`
    once it did - `False` is a CRITICAL outcome (Part 2's explicit
    "never silently report success when exposure remains"), logged as
    such, never silently swallowed."""


def check_and_trigger_automatic_square_off(
    *, current_prices: dict[str, Decimal], now: datetime | None = None
) -> AutomaticSquareOffCheckOutcome:
    """Checkpoint 46's own required chain, in one function:
    KILL_SWITCH_ENGAGED -> DETECT -> (if claimable) AUTOMATIC
    SQUARE-OFF -> RECONCILIATION -> VERIFY ZERO EXPOSURE -> record
    outcome durably. Called from BOTH the scheduled ingestion tick and
    the independent 15s task (Checkpoint 47 Part 4) - both routes go
    through the SAME `claim()` call below, which is what makes it safe
    for both to exist at once.

    Checkpoint 48 Part 3: `already_handled=True` now means exactly what
    it says - the halt event reached `COMPLETED` (square-off ran AND
    reconciliation confirmed zero exposure), not merely "an attempt was
    claimed." A `FAILED_RETRYABLE` or `RECONCILIATION_REQUIRED` row, or
    a stale `IN_PROGRESS` row from a crashed attempt, is reclaimed and
    retried here instead of being reported as handled."""
    clock = now or datetime.now(tz=UTC)
    kill_switch_service = KillSwitchService(DjangoKillSwitchRepository())
    state = kill_switch_service.status()

    if state.status is not TradingHaltStatus.HALTED:
        return AutomaticSquareOffCheckOutcome(
            kill_switch_engaged=False,
            already_handled=False,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=None,
        )

    halt_identity = state.changed_at.isoformat() if state.changed_at else "unknown"
    event_repository = DjangoEmergencySquareOffEventRepository()
    claim = event_repository.claim(halt_identity=halt_identity, now=clock)

    if not claim.claimed:
        # Either COMPLETED already (genuinely done - report handled),
        # or a fresh IN_PROGRESS claim held by a concurrent caller right
        # now (not terminal - just nothing to do THIS call).
        return AutomaticSquareOffCheckOutcome(
            kill_switch_engaged=True,
            already_handled=claim.already_terminal,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=None,
        )

    logger.warning(
        "emergency_square_off.auto_triggered",
        reason=state.reason,
        changed_at=halt_identity,
        attempt_count=claim.attempt_count,
    )

    try:
        square_off = run_emergency_square_off(current_prices=current_prices, now=clock)
    except Exception as exc:  # noqa: BLE001 - a raised exception must still be recorded, not crash the caller silently
        logger.exception("emergency_square_off.attempt_raised")
        event_repository.mark_failed_retryable(
            halt_identity=halt_identity,
            positions_closed=0,
            positions_failed=[],
            reconciliation_divergence_count=None,
            error=repr(exc),
        )
        return AutomaticSquareOffCheckOutcome(
            kill_switch_engaged=True,
            already_handled=False,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=False,
        )

    reconciliation_divergence_count: int | None = None
    try:
        report = reconcile_paper_state(
            broker=get_paper_broker(), ledger=DjangoPaperLedgerRepository(), now=clock
        )
        reconciliation_divergence_count = report.total_divergence_count
    except Exception:  # noqa: BLE001 - a reconciliation failure must still surface, not crash the trigger
        logger.exception("emergency_square_off.post_square_off_reconciliation_failed")

    remaining_open = len(
        [p for p in get_paper_broker().get_positions() if p.status.value == "OPEN"]
    )
    zero_exposure_confirmed = remaining_open == 0 and not square_off.positions_failed

    if square_off.positions_failed:
        logger.error(
            "emergency_square_off.exposure_remains_after_square_off",
            remaining_open_positions=remaining_open,
            positions_failed=square_off.positions_failed,
        )
        event_repository.mark_failed_retryable(
            halt_identity=halt_identity,
            positions_closed=square_off.positions_closed,
            positions_failed=list(square_off.positions_failed),
            reconciliation_divergence_count=reconciliation_divergence_count,
            error="one or more positions could not be closed this attempt",
        )
    elif not zero_exposure_confirmed or (
        reconciliation_divergence_count is not None and reconciliation_divergence_count > 0
    ):
        # Every attempted position closed, but exposure/reconciliation
        # still disagrees - flagged distinctly (see
        # `EmergencySquareOffEvent`'s docstring) rather than treated as
        # an ordinary retryable exit failure.
        logger.error(
            "emergency_square_off.reconciliation_required_after_square_off",
            remaining_open_positions=remaining_open,
            reconciliation_divergence_count=reconciliation_divergence_count,
        )
        event_repository.mark_reconciliation_required(
            halt_identity=halt_identity,
            positions_closed=square_off.positions_closed,
            reconciliation_divergence_count=reconciliation_divergence_count,
        )
    else:
        logger.warning("emergency_square_off.completed_zero_exposure_confirmed")
        event_repository.mark_completed(
            halt_identity=halt_identity,
            positions_closed=square_off.positions_closed,
            reconciliation_divergence_count=reconciliation_divergence_count,
            now=clock,
        )

    return AutomaticSquareOffCheckOutcome(
        kill_switch_engaged=True,
        already_handled=False,
        square_off=square_off,
        reconciliation_divergence_count=reconciliation_divergence_count,
        zero_exposure_confirmed=zero_exposure_confirmed,
    )
