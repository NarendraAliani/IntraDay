# File: src/intraday/infrastructure/api/emergency_square_off_trigger.py
#
# Checkpoint 46 Part 2: closes THE named P0 gap from Checkpoint 45's
# own register - `run_emergency_square_off()` existed and was tested,
# but nothing automatically invoked it when the kill switch engaged.
# This module is that automatic trigger.
#
# Idempotency (Part 2's explicit requirement #2/#3/#4): keyed off the
# kill switch's own `changed_at` timestamp - the ONE moment a
# particular halt event occurred. Uses the same Django-cache
# atomic-add primitive `infrastructure/scheduling/distributed_lock.py`
# already established (Decision 187) - a SEPARATE cache key namespace
# (`intraday:square_off_handled:`) so it does not collide with the
# ingestion-tick concurrency lock, and a long timeout (24h) since a
# halt event's identity (`changed_at`) never changes for that event -
# once handled, it must never be re-handled, unlike the 90s
# ingestion-tick lock which is deliberately short-lived.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from django.core.cache import cache

from intraday.application.services.kill_switch import KillSwitchService
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.api.paper_trading_runtime import get_paper_broker
from intraday.infrastructure.api.position_monitor_runtime import (
    EmergencySquareOffOutcome,
    run_emergency_square_off,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)

logger = structlog.get_logger(__name__)

_SQUARE_OFF_HANDLED_KEY_PREFIX = "intraday:square_off_handled:"
_SQUARE_OFF_HANDLED_TIMEOUT_SECONDS = 24 * 60 * 60  # 24h - see module docstring


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
    KILL_SWITCH_ENGAGED -> DETECT -> (if not already handled)
    AUTOMATIC SQUARE-OFF -> RECONCILIATION -> VERIFY ZERO EXPOSURE.
    Called from the scheduled ingestion tick (Part 8/24's "the
    backend/control plane must own this behavior," never a UI-only
    action)."""
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
    cache_key = f"{_SQUARE_OFF_HANDLED_KEY_PREFIX}{halt_identity}"
    claimed = cache.add(cache_key, "1", timeout=_SQUARE_OFF_HANDLED_TIMEOUT_SECONDS)

    if not claimed:
        # This exact halt event was already square-off'd - never
        # re-run it (Part 2's explicit "must not create duplicate
        # exits" / "exactly once for a given halt event").
        return AutomaticSquareOffCheckOutcome(
            kill_switch_engaged=True,
            already_handled=True,
            square_off=None,
            reconciliation_divergence_count=None,
            zero_exposure_confirmed=None,
        )

    logger.warning(
        "emergency_square_off.auto_triggered", reason=state.reason, changed_at=halt_identity
    )
    square_off = run_emergency_square_off(current_prices=current_prices, now=clock)

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

    if not zero_exposure_confirmed:
        logger.error(
            "emergency_square_off.exposure_remains_after_square_off",
            remaining_open_positions=remaining_open,
            positions_failed=square_off.positions_failed,
        )
    else:
        logger.warning("emergency_square_off.completed_zero_exposure_confirmed")

    return AutomaticSquareOffCheckOutcome(
        kill_switch_engaged=True,
        already_handled=False,
        square_off=square_off,
        reconciliation_divergence_count=reconciliation_divergence_count,
        zero_exposure_confirmed=zero_exposure_confirmed,
    )
