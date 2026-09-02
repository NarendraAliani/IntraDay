# File: src/intraday/domain/market_data/migration_audit.py
#
# Checkpoint 67.7 Part 7 (audit-mapping data contract) and Part 11
# (algebraic rollback arithmetic). Per the directive's own allowance
# ("if persistent creation is too large for this checkpoint, implement
# and test the exact data contract without populating it"), THIS
# CHECKPOINT DOES NOT CREATE A PERSISTENT DB TABLE for audit rows — no
# migration adds a model, no row is ever inserted into any table by
# this module. `MigrationAuditRecord` below is a plain, frozen,
# in-memory dataclass; the dry-run runner constructs instances of it
# purely to report projected mappings, never to persist them. This is
# the safer choice per the checkpoint's HARD RULE ("NO INSERT audit
# rows if that would alter production DB") — even a well-intentioned
# audit table is still a write to a production database table, and
# this checkpoint's whole point is that NOTHING writes anywhere.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from intraday.domain.market_data.migration_state import MigrationRunState, MigrationUnitState
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


@dataclass(frozen=True, slots=True)
class MigrationAuditRecord:
    """The minimum required audit structure (Part 7): one record per
    `HistoricalBar` row a migration run would touch. Uniqueness (if
    this were ever persisted) is `(migration_id, row_id)` — enforced
    here only as a set-based check in
    `assert_unique_migration_row_pairs`, since no table/constraint
    exists to enforce it at the DB level in this checkpoint.

    `old_timestamp` is carried verbatim (never derived from
    `new_timestamp` after the fact) so it "MUST remain reconstructable
    after migration" (Part 7) even though, in dry-run, nothing is ever
    written — the field exists so a FUTURE real migration run, using
    this exact contract, satisfies that requirement from the moment it
    starts persisting rows."""

    migration_id: str
    row_id: int
    instrument_id: InstrumentId
    timeframe: Timeframe
    old_timestamp: datetime
    new_timestamp: datetime
    source_semantics: str
    proof_scope: str
    status: MigrationUnitState
    applied_at: datetime | None
    """`None` for every record a dry-run run produces — Part 7's
    `applied_at` field only becomes non-`None` once a real commit
    happens, which never occurs in this checkpoint."""


# --------------------------------------------------------------------
# Checkpoint 67.8 Part 9 — PERSISTENT AUDIT MODEL, DESIGN ONLY.
#
# Deliberately still plain, frozen dataclasses, NOT Django models: no
# migration is run by this checkpoint, so no production table is
# created, per the directive's own explicit allowance ("design the
# exact data contract without populating it" when persistent creation
# is out of scope) and this codebase's own HARD RULE ("NO production
# audit writes"). A future write-capable checkpoint can turn these
# three dataclasses into three Django models with a single additive
# migration (three new tables, no change to any existing table/
# constraint) without altering this contract's shape - the field names
# and types below ARE the intended column list.
#
# Three levels, matching the directive's minimum exactly:
#   RUN  - one row per migration execution.
#   UNIT - one row per (instrument_id, timeframe, trading_date) unit
#          touched by that run.
#   ROW  - one row per HistoricalBar row touched by that unit
#          (`MigrationAuditRecord` above already satisfies this level -
#          it predates this Part but its shape already matches: it
#          carries `migration_id`, a `row_id`, both timestamps, and
#          `status`).
# Required uniqueness `(migration_id, row_id)` is already enforced (in
# memory) by `assert_unique_migration_row_pairs` below for the ROW
# level; the RUN and UNIT dataclasses add their own analogous
# uniqueness helpers.
@dataclass(frozen=True, slots=True)
class MigrationRunAuditRecord:
    """RUN-level audit record. `migration_id` is the natural key (one
    row per run) - a real table would make it the primary key or add a
    surrogate `id` with `migration_id` UNIQUE."""

    migration_id: str
    status: MigrationRunState
    started_at: datetime
    completed_at: datetime | None
    """`None` while the run is not yet in a terminal state
    (COMPLETED/ABORTED); populated the instant it reaches one."""
    migration_version: str
    scope: str
    """Human-readable description of what this run covers, e.g. the
    same eligibility description the 67.7 dry-run report already
    computes (`"CAS-era NSE 5m OPEN->CLOSE canonicalization"`)."""


@dataclass(frozen=True, slots=True)
class MigrationUnitAuditRecord:
    """UNIT-level audit record - one per `(instrument_id, timeframe,
    trading_date)` unit within a run. `(migration_id, unit_id)` is the
    natural key; `unit_id` is expected to be a deterministic string
    derived from `(instrument_id, timeframe, trading_date)`, matching
    how `migration_dry_run.py` already identifies units."""

    migration_id: str
    unit_id: str
    instrument_id: InstrumentId
    timeframe: Timeframe
    trading_date: date
    status: MigrationUnitState
    old_row_count: int
    new_row_count: int
    error_code: str | None
    committed_at: datetime | None
    """`None` unless `status is MigrationUnitState.COMMITTED`."""


def assert_unique_migration_run_ids(records: tuple[MigrationRunAuditRecord, ...]) -> None:
    """RUN-level uniqueness: `migration_id` alone (one run record per
    run)."""
    seen: set[str] = set()
    for record in records:
        if record.migration_id in seen:
            raise ValueError(f"duplicate migration_id in RUN audit records: {record.migration_id}")
        seen.add(record.migration_id)


def assert_unique_migration_unit_pairs(records: tuple[MigrationUnitAuditRecord, ...]) -> None:
    """UNIT-level uniqueness: `(migration_id, unit_id)`."""
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (record.migration_id, record.unit_id)
        if key in seen:
            raise ValueError(f"duplicate (migration_id, unit_id) audit key: {key}")
        seen.add(key)


def assert_unique_migration_row_pairs(records: tuple[MigrationAuditRecord, ...]) -> None:
    """Part 6's uniqueness requirement `(migration_id, row_id)`,
    checked in memory since no DB table exists to enforce it here.
    Raises on any duplicate rather than silently deduplicating."""
    seen: set[tuple[str, int]] = set()
    for record in records:
        key = (record.migration_id, record.row_id)
        if key in seen:
            raise ValueError(f"duplicate (migration_id, row_id) audit key: {key}")
        seen.add(key)


def forward_shift(old_timestamp: datetime, interval: timedelta) -> datetime:
    """The projected OPEN->CLOSE canonicalization shift: identical
    arithmetic to `source_timestamp.canonicalize_close_timestamp` for
    the `OPEN` case (`raw + interval`), duplicated here ONLY as a pure,
    dependency-free primitive for the rollback-algebra proof below —
    never used to write anything."""
    return old_timestamp + interval


def rollback_shift(new_timestamp: datetime, interval: timedelta) -> datetime:
    """The algebraic inverse of `forward_shift` — `new - interval`.
    Part 11 explicitly calls this "ALGEBRAIC ROLLBACK VALIDATION" (pure
    arithmetic proof), NOT "DB-level rollback validation" (which would
    require an actual write-then-undo and is out of scope for a
    dry-run runner that performs zero writes)."""
    return new_timestamp - interval


def verify_algebraic_rollback(old_timestamp: datetime, interval: timedelta) -> bool:
    """`rollback(forward(old)) == old` — Part 11's required identity,
    checked directly rather than assumed."""
    return rollback_shift(forward_shift(old_timestamp, interval), interval) == old_timestamp


__all__ = [
    "MigrationAuditRecord",
    "MigrationRunAuditRecord",
    "MigrationUnitAuditRecord",
    "assert_unique_migration_row_pairs",
    "assert_unique_migration_run_ids",
    "assert_unique_migration_unit_pairs",
    "forward_shift",
    "rollback_shift",
    "verify_algebraic_rollback",
]
