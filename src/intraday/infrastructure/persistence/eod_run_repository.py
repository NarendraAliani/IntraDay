# File: src/intraday/infrastructure/persistence/eod_run_repository.py
#
# Checkpoint 51 Part 11: the repository owning `EODRun`'s state
# transitions. Deliberately near-identical in shape to
# `emergency_square_off_event_repository.py` (Checkpoint 48) - the
# crash-recovery lesson learned there (a cache-only claim can strand a
# safety-critical operation as falsely "handled") applies identically
# to EOD, which also force-closes every open PAPER position.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from django.db import transaction

from intraday.infrastructure.persistence.models import EODRun

# Mirrors IN_PROGRESS_STALENESS_SECONDS in
# emergency_square_off_event_repository.py - same rationale: long
# enough that a genuinely still-running attempt is never falsely
# reclaimed, short enough that a crashed attempt is retried promptly
# rather than sitting stuck. EOD is a once-per-day operation, so a
# slightly longer window than the 15s-cadence emergency check is
# appropriate here.
EOD_IN_PROGRESS_STALENESS_SECONDS = 300


class EODRunStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"


_TERMINAL = {EODRunStatus.COMPLETED}


@dataclass(frozen=True, slots=True)
class EODClaimResult:
    claimed: bool
    already_terminal: bool
    attempt_count: int


class DjangoEODRunRepository:
    """Django ORM implementation of the EOD durable state machine -
    claim/complete/fail, exactly the same three operations
    `DjangoEmergencySquareOffEventRepository` exposes, for the same
    reason (every legal transition this domain needs is one of exactly
    those three)."""

    @transaction.atomic
    def claim(self, *, eod_date: dt.date, now: dt.datetime) -> EODClaimResult:
        row, _created = EODRun.objects.select_for_update().get_or_create(eod_date=eod_date)
        status = EODRunStatus(row.status)

        if status in _TERMINAL:
            return EODClaimResult(
                claimed=False, already_terminal=True, attempt_count=row.attempt_count
            )

        if status is EODRunStatus.IN_PROGRESS:
            claimed_at = row.claimed_at
            is_stale = claimed_at is None or (now - claimed_at).total_seconds() > (
                EOD_IN_PROGRESS_STALENESS_SECONDS
            )
            if not is_stale:
                return EODClaimResult(
                    claimed=False, already_terminal=False, attempt_count=row.attempt_count
                )
            # Stale IN_PROGRESS - reclaim (the previous attempt crashed
            # before reaching complete()/fail()).

        row.status = EODRunStatus.IN_PROGRESS.value
        row.claimed_at = now
        row.attempt_count += 1
        row.save(update_fields=["status", "claimed_at", "attempt_count", "updated_at"])
        return EODClaimResult(claimed=True, already_terminal=False, attempt_count=row.attempt_count)

    @transaction.atomic
    def mark_completed(
        self,
        *,
        eod_date: dt.date,
        positions_closed: int,
        reconciliation_divergence_count: int | None,
        total_realized_pnl: Decimal,
        now: dt.datetime,
    ) -> None:
        row = EODRun.objects.select_for_update().get(eod_date=eod_date)
        row.status = EODRunStatus.COMPLETED.value
        row.completed_at = now
        row.positions_closed = positions_closed
        row.positions_failed = []
        row.reconciliation_divergence_count = reconciliation_divergence_count
        row.total_realized_pnl = total_realized_pnl
        row.last_error = ""
        row.save(
            update_fields=[
                "status",
                "completed_at",
                "positions_closed",
                "positions_failed",
                "reconciliation_divergence_count",
                "total_realized_pnl",
                "last_error",
                "updated_at",
            ]
        )

    @transaction.atomic
    def mark_failed_retryable(
        self,
        *,
        eod_date: dt.date,
        positions_closed: int,
        positions_failed: list[str],
        reconciliation_divergence_count: int | None,
        error: str,
    ) -> None:
        row = EODRun.objects.select_for_update().get(eod_date=eod_date)
        row.status = EODRunStatus.FAILED_RETRYABLE.value
        row.positions_closed = positions_closed
        row.positions_failed = positions_failed
        row.reconciliation_divergence_count = reconciliation_divergence_count
        row.last_error = error[:1000]
        row.save(
            update_fields=[
                "status",
                "positions_closed",
                "positions_failed",
                "reconciliation_divergence_count",
                "last_error",
                "updated_at",
            ]
        )
