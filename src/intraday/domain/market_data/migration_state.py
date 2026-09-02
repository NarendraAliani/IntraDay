# File: src/intraday/domain/market_data/migration_state.py
#
# Checkpoint 67.7 Part 6 — the migration STATE MACHINE vocabulary for
# the timestamp-canonicalization migration designed in 67.6 and given
# an executable DRY-RUN-ONLY runner in this checkpoint
# (`application.services.migration_dry_run`). Two independent state
# machines, exactly as the directive specifies:
#
#   `MigrationRunState`  — one value for the WHOLE migration run.
#   `MigrationUnitState` — one value PER (instrument, timeframe,
#                          trading_date) migration unit.
#
# Deliberately just enums plus tiny pure helpers — no persistence, no
# transition engine — because this checkpoint's dry-run runner only
# ever reaches a narrow subset of these states (PLANNED, and per-unit
# PENDING -> DRY_RUN_SAFE or a STOPPED/FAILED terminal state); the
# COMMITTED/ROLLED_BACK states (and run-level RUNNING/PARTIALLY_
# COMPLETED/COMPLETED/ABORTED) require an actual write and are
# therefore UNREACHABLE by any code path in this checkpoint — see
# `MigrationDryRunResult` for the explicit assertion that no dry-run
# ever produces one of those.
from __future__ import annotations

import enum


class MigrationRunState(enum.Enum):
    """Run-level state. A dry-run execution may only ever produce
    `PLANNED` (the enumeration/validation phase this checkpoint
    implements) or `ABORTED` (if a safety guard trips). `RUNNING`,
    `PARTIALLY_COMPLETED`, and `COMPLETED` all require at least one
    committed write and are structurally unreachable from
    `--dry-run`."""

    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


DRY_RUN_REACHABLE_RUN_STATES = frozenset({MigrationRunState.PLANNED, MigrationRunState.ABORTED})
"""The only `MigrationRunState` members a `--dry-run` execution is
permitted to end in — asserted by the dry-run runner itself and by
`test_migration_67_7_dry_run.py`."""


class MigrationUnitState(enum.Enum):
    """Unit-level state, one per `(instrument_id, timeframe,
    trading_date)` migration unit. `COMMITTED` and `ROLLED_BACK` both
    require an actual `HistoricalBar` write; dry-run can only ever
    reach `PENDING` (not yet evaluated), `DRY_RUN_SAFE` (revalidated,
    would be safe to migrate), or one of the two failure terminals
    (`STOPPED_REVALIDATION_MISMATCH`, `FAILED`)."""

    PENDING = "PENDING"
    DRY_RUN_SAFE = "DRY_RUN_SAFE"
    """Dry-run-only terminal state (67.7) - NOT part of the full
    write-capable unit state machine's transition table below (Part 8
    finalizes REVALIDATING/SAFE/MIGRATING instead); kept as its own
    enum member so 67.7's dry-run runner and its existing tests are
    completely unaffected by this checkpoint's additions."""
    REVALIDATING = "REVALIDATING"
    """Checkpoint 67.8 Part 8: a real (write-capable) migration run has
    re-read this unit's current DB state, immediately before deciding
    whether it is still safe to migrate."""
    SAFE = "SAFE"
    """Revalidation passed against the CURRENT database - the unit may
    proceed to MIGRATING. Distinct from `DRY_RUN_SAFE`: reaching `SAFE`
    means a real migration is about to attempt a write; `DRY_RUN_SAFE`
    can never lead to a write in this codebase."""
    MIGRATING = "MIGRATING"
    """The advisory lock for this unit's (instrument_id, timeframe) is
    held and the descending-order UPDATE sequence is in flight, inside
    an open, uncommitted database transaction."""
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    STOPPED_REVALIDATION_MISMATCH = "STOPPED_REVALIDATION_MISMATCH"
    FAILED = "FAILED"


DRY_RUN_REACHABLE_UNIT_STATES = frozenset(
    {
        MigrationUnitState.PENDING,
        MigrationUnitState.DRY_RUN_SAFE,
        MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
        MigrationUnitState.FAILED,
    }
)
"""The only `MigrationUnitState` members a `--dry-run` execution is
permitted to assign to any unit — `COMMITTED`/`ROLLED_BACK` require a
real write and are structurally unreachable here."""


RUN_STATE_TRANSITIONS: frozenset[tuple[MigrationRunState, MigrationRunState]] = frozenset(
    {
        (MigrationRunState.PLANNED, MigrationRunState.RUNNING),
        (MigrationRunState.RUNNING, MigrationRunState.PARTIALLY_COMPLETED),
        (MigrationRunState.RUNNING, MigrationRunState.COMPLETED),
        (MigrationRunState.RUNNING, MigrationRunState.ABORTED),
        (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.RUNNING),
        (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.ABORTED),
        (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.COMPLETED),
    }
)
"""Checkpoint 67.8 Part 7 — the exact, closed set of legal run-level
transitions, verbatim from the directive's own example table. `PLANNED`
is the only entry state (no transition INTO it). `COMPLETED` and
`ABORTED` are terminal (no transition OUT of either). Any pair not in
this set is illegal, including every same-state "transition" (no
self-loops) and both directions not explicitly listed (e.g. `PLANNED`
-> anything but `RUNNING`, or `COMPLETED`/`ABORTED` -> anything)."""


def is_legal_run_transition(
    current: MigrationRunState, target: MigrationRunState
) -> bool:
    """Pure predicate over `RUN_STATE_TRANSITIONS` — the run-state
    machine's only decision rule. No side effects, no persistence."""
    return (current, target) in RUN_STATE_TRANSITIONS


UNIT_STATE_TRANSITIONS: frozenset[tuple[MigrationUnitState, MigrationUnitState]] = frozenset(
    {
        (MigrationUnitState.PENDING, MigrationUnitState.REVALIDATING),
        (MigrationUnitState.REVALIDATING, MigrationUnitState.SAFE),
        (MigrationUnitState.REVALIDATING, MigrationUnitState.STOPPED_REVALIDATION_MISMATCH),
        (MigrationUnitState.REVALIDATING, MigrationUnitState.FAILED),
        (MigrationUnitState.SAFE, MigrationUnitState.MIGRATING),
        (MigrationUnitState.SAFE, MigrationUnitState.STOPPED_REVALIDATION_MISMATCH),
        (MigrationUnitState.MIGRATING, MigrationUnitState.COMMITTED),
        (MigrationUnitState.MIGRATING, MigrationUnitState.ROLLED_BACK),
        (MigrationUnitState.MIGRATING, MigrationUnitState.FAILED),
    }
)
"""Checkpoint 67.8 Part 8 — the exact, closed set of legal unit-level
transitions. `PENDING` is the only entry state. `COMMITTED`,
`ROLLED_BACK`, `STOPPED_REVALIDATION_MISMATCH`, and `FAILED` are all
terminal (no transition out of any of them) - a unit that failed,
mismatched on revalidation, or was rolled back is never silently
retried in place; a fresh unit (new PENDING) would be required.
`SAFE` -> `STOPPED_REVALIDATION_MISMATCH` covers the case where a
second, immediately-pre-commit revalidation (a live DB row appeared
between the first REVALIDATING pass and the MIGRATING attempt) catches
a mismatch that the first pass could not have seen."""


def is_legal_unit_transition(
    current: MigrationUnitState, target: MigrationUnitState
) -> bool:
    """Pure predicate over `UNIT_STATE_TRANSITIONS`."""
    return (current, target) in UNIT_STATE_TRANSITIONS


def assert_dry_run_state_reachable(state: MigrationRunState | MigrationUnitState) -> None:
    """Fails loudly (never silently) if a dry-run code path ever
    produces a state that requires an actual write. Called by the
    runner immediately before returning its result — defense in depth
    alongside the write-guard in `migration_dry_run.py`."""
    if isinstance(state, MigrationRunState):
        if state not in DRY_RUN_REACHABLE_RUN_STATES:
            raise AssertionError(
                f"dry-run produced run-level state {state!r}, which requires an actual "
                "HistoricalBar write and is structurally unreachable from --dry-run"
            )
        return
    if isinstance(state, MigrationUnitState):
        if state not in DRY_RUN_REACHABLE_UNIT_STATES:
            raise AssertionError(
                f"dry-run produced unit-level state {state!r}, which requires an actual "
                "HistoricalBar write and is structurally unreachable from --dry-run"
            )
        return
    raise TypeError(f"not a migration state: {state!r}")


__all__ = [
    "MigrationRunState",
    "MigrationUnitState",
    "DRY_RUN_REACHABLE_RUN_STATES",
    "DRY_RUN_REACHABLE_UNIT_STATES",
    "RUN_STATE_TRANSITIONS",
    "UNIT_STATE_TRANSITIONS",
    "is_legal_run_transition",
    "is_legal_unit_transition",
    "assert_dry_run_state_reachable",
]
