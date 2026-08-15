# File: src/intraday/infrastructure/persistence/emergency_square_off_event_repository.py
#
# Checkpoint 48 Part 3: the repository owning `EmergencySquareOffEvent`'s
# state transitions - all of them wrapped in `select_for_update()` inside
# `transaction.atomic()` so two concurrent callers (the ingestion tick's
# call AND the independent 15s task's call, which Checkpoint 47 Part 4
# deliberately made BOTH able to trigger square-off) can never both
# successfully claim the same halt event.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from django.db import transaction

from intraday.infrastructure.persistence.models import EmergencySquareOffEvent

# An IN_PROGRESS row whose claim is older than this is treated as an
# abandoned/crashed attempt and reclaimed by the next caller - this is
# the concrete mechanism that makes the state machine restart-safe.
# 120s is deliberately several multiples of the 15s independent-task
# cadence (Checkpoint 47 Part 4) - long enough that a genuinely still-
# running attempt is never falsely reclaimed out from under itself, short
# enough that a crashed attempt is retried within a couple of minutes
# rather than sitting stuck for the full 24h the old cache TTL used.
IN_PROGRESS_STALENESS_SECONDS = 120


class SquareOffEventStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


_TERMINAL = {SquareOffEventStatus.COMPLETED}


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claimed: bool
    already_terminal: bool
    """`True` when the halt event is already `COMPLETED` - the caller
    must not attempt anything further, matching the OLD cache-based
    `already_handled=True` outcome exactly for this one case."""
    event_id: int | None
    attempt_count: int


class DjangoEmergencySquareOffEventRepository:
    """Django ORM implementation of the emergency-square-off durable
    state machine. Deliberately narrow - three operations
    (claim/complete/fail) rather than a general-purpose CRUD surface,
    since every legal transition this domain needs is one of exactly
    those three."""

    @transaction.atomic
    def claim(self, *, halt_identity: str, now: dt.datetime) -> ClaimResult:
        """Atomically claims the right to run (or re-run) square-off for
        `halt_identity`. `select_for_update()` inside `transaction.atomic()`
        serializes concurrent callers against the SAME database row - the
        second concurrent caller blocks until the first commits, then sees
        the first's now-`IN_PROGRESS`, non-stale row and is correctly
        refused the claim."""
        row, _created = EmergencySquareOffEvent.objects.select_for_update().get_or_create(
            halt_identity=halt_identity
        )

        status = SquareOffEventStatus(row.status)
        if status in _TERMINAL:
            return ClaimResult(
                claimed=False,
                already_terminal=True,
                event_id=row.pk,
                attempt_count=row.attempt_count,
            )

        if status is SquareOffEventStatus.IN_PROGRESS:
            claimed_at = row.claimed_at
            is_stale = claimed_at is None or (now - claimed_at).total_seconds() > (
                IN_PROGRESS_STALENESS_SECONDS
            )
            if not is_stale:
                # A genuinely concurrent attempt is running right now -
                # refuse the claim, but this is NOT terminal (the caller
                # should simply do nothing this tick, not treat it as done).
                return ClaimResult(
                    claimed=False,
                    already_terminal=False,
                    event_id=row.pk,
                    attempt_count=row.attempt_count,
                )
            # Stale IN_PROGRESS - the previous attempt crashed before
            # reaching complete()/fail(). Reclaim it. This is the exact
            # crash-recovery path: nothing marked this "handled" when the
            # process died, so the row is still sitting here, reclaimable.

        row.status = SquareOffEventStatus.IN_PROGRESS.value
        row.claimed_at = now
        row.attempt_count += 1
        row.save(update_fields=["status", "claimed_at", "attempt_count", "updated_at"])
        return ClaimResult(
            claimed=True, already_terminal=False, event_id=row.pk, attempt_count=row.attempt_count
        )

    @transaction.atomic
    def mark_completed(
        self,
        *,
        halt_identity: str,
        positions_closed: int,
        reconciliation_divergence_count: int | None,
        now: dt.datetime,
    ) -> None:
        """Terminal success: square-off ran AND zero open exposure was
        confirmed by reconciliation. Never re-run once here."""
        row = EmergencySquareOffEvent.objects.select_for_update().get(halt_identity=halt_identity)
        row.status = SquareOffEventStatus.COMPLETED.value
        row.completed_at = now
        row.positions_closed = positions_closed
        row.positions_failed = []
        row.reconciliation_divergence_count = reconciliation_divergence_count
        row.last_error = ""
        row.save(
            update_fields=[
                "status",
                "completed_at",
                "positions_closed",
                "positions_failed",
                "reconciliation_divergence_count",
                "last_error",
                "updated_at",
            ]
        )

    @transaction.atomic
    def mark_failed_retryable(
        self,
        *,
        halt_identity: str,
        positions_closed: int,
        positions_failed: list[str],
        reconciliation_divergence_count: int | None,
        error: str,
    ) -> None:
        """Not terminal - the next claim() call is expected to retry this
        halt event. Used both when `run_emergency_square_off()` itself
        reports failed positions AND when an unexpected exception is
        raised mid-run (caught by the trigger, never left to crash the
        caller silently without recording SOMETHING)."""
        row = EmergencySquareOffEvent.objects.select_for_update().get(halt_identity=halt_identity)
        row.status = SquareOffEventStatus.FAILED_RETRYABLE.value
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

    @transaction.atomic
    def mark_reconciliation_required(
        self,
        *,
        halt_identity: str,
        positions_closed: int,
        reconciliation_divergence_count: int | None,
    ) -> None:
        """Square-off itself succeeded (no failed positions), but POST
        reconciliation still shows a divergence - flagged distinctly from
        FAILED_RETRYABLE since blindly resubmitting exit orders is not
        obviously correct here (see class docstring on
        `EmergencySquareOffEvent`). Still reclaimable by the next tick."""
        row = EmergencySquareOffEvent.objects.select_for_update().get(halt_identity=halt_identity)
        row.status = SquareOffEventStatus.RECONCILIATION_REQUIRED.value
        row.positions_closed = positions_closed
        row.positions_failed = []
        row.reconciliation_divergence_count = reconciliation_divergence_count
        row.save(
            update_fields=[
                "status",
                "positions_closed",
                "positions_failed",
                "reconciliation_divergence_count",
                "updated_at",
            ]
        )
