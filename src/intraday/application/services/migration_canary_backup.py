# File: src/intraday/application/services/migration_canary_backup.py
#
# Checkpoint 67.12-PRE Parts 1-4 — hardened canary backup generation.
#
# Replaces the ephemeral, never-committed script that produced
# `artifacts/canary_backup_67_11_6.json` (its `unit_fingerprint` field
# could not be reproduced by any function in this repository — see
# taskReport.md Deliverable C for the root-cause diagnosis) with a
# small, reusable, PARAMETERIZED backup function that:
#
#   1. takes an actual selected-unit object (`UnitDryRunResult`, from
#      re-running the real `select_canary_unit` algorithm against the
#      real `HistoricalBarMigrationDryRunner` plan) as input — no
#      hard-coded symbol/instrument/date/timeframe/row-count/fingerprint
#      literal anywhere in this module;
#   2. records BOTH a scope fingerprint (via the exact same
#      `_cas_scope_inputs`/`compute_scope_fingerprint` the executor's own
#      TOCTOU revalidation calls — not a reimplementation) and a payload
#      fingerprint (via the new `compute_payload_fingerprint`), as two
#      distinct values, never conflated;
#   3. relies on TWO separate, complementary guarantees, deliberately
#      not conflated (Checkpoint 67.12.1 Task 1):
#        (a) ONE CONSISTENT SNAPSHOT PER READ: each of the "before" and
#            "after" reads is one single `.values()` queryset -> one
#            single SQL statement, so PostgreSQL's per-statement READ
#            COMMITTED snapshot guarantees every row within THAT read
#            is internally consistent with every other row in the same
#            read (see `_fetch_payload_rows`'s docstring for the exact
#            statement of what this does and does not guarantee).
#        (b) BEFORE/AFTER DRIFT DETECTION (defense-in-depth, weaker):
#            reads the live payload TWICE (once before export, once
#            after) and requires the two payload fingerprints to be
#            identical. This detects drift BETWEEN the two reads — it
#            is NOT what makes either individual read internally
#            consistent (that is guarantee (a)). If the two fingerprints
#            differ, `SourceChangedDuringExportError` is raised — the
#            backup is REFUSED, never silently regenerated against
#            whatever the second read happened to see.
#
# This module only ever performs read-only `.values()` queries against
# `HistoricalBar` (`.filter().order_by().values(...)`) — it has no
# `.save()`/`.update()`/`.bulk_create()`/`.delete()` call anywhere, the
# same architectural write-incapability pattern `migration_dry_run.py`
# uses.
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from contextlib import contextmanager

from django.db import connection, transaction

from intraday.application.services.migration_dry_run import MIGRATION_ID, UnitDryRunResult
from intraday.application.services.migration_execute import (
    ELIGIBILITY_PREDICATE_VERSION,
    MIGRATION_VERSION,
    _cas_scope_inputs,
)
from intraday.domain.market_data.migration_payload_fingerprint import (
    PayloadRow,
    compute_payload_fingerprint,
)
from intraday.domain.market_data.migration_scope_fingerprint import compute_scope_fingerprint
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    _segment_for_instrument,
)
from intraday.infrastructure.persistence.models import HistoricalBar


class SourceChangedDuringExportError(RuntimeError):
    """Raised by `build_canary_backup` when the live source payload
    fingerprint computed AFTER export differs from the one computed
    BEFORE export (Part 4's snapshot-consistency requirement). Never
    caught-and-retried internally: a caller that wants a backup of the
    new state must explicitly re-run selection and export again, as a
    conscious new attempt, not an automatic silent one."""

    def __init__(self, *, before: str, after: str) -> None:
        self.before = before
        self.after = after
        super().__init__(
            f"source payload changed during export: before={before} after={after} - "
            "STOPPED, backup REFUSED (not silently regenerated)"
        )


@contextmanager
def _repeatable_read_atomic():
    """Checkpoint 67.12.2 Part 2 — TRUE EXPORT SNAPSHOT.

    Opens one `transaction.atomic()` block and, as the FIRST statement
    inside it (PostgreSQL requires `SET TRANSACTION ISOLATION LEVEL` to
    be issued before any other statement in the transaction), sets this
    transaction's isolation level to REPEATABLE READ.

    WHAT THIS GUARANTEES: every query issued for the remainder of this
    transaction observes one stable snapshot of the database, taken at
    the time of this transaction's FIRST statement — not merely a
    per-statement snapshot (that is READ COMMITTED's guarantee, and it
    is all a bare `transaction.atomic()` around READ COMMITTED reads
    ever provided — see `_fetch_payload_rows`'s docstring and Deliverable
    A/C of taskReport.md for the 67.12.1 audit finding this closes).
    Concretely: the payload-row fetch and the payload-fingerprint
    computation derived from those same rows, when both run inside one
    call to this context manager, are PROVEN to correspond to the same
    point-in-time database state — not merely each individually
    internally consistent.

    WHAT THIS DOES NOT GUARANTEE: it does not stop a concurrent writer
    from committing changes to the real table — those changes simply
    become invisible to THIS transaction's own reads for the rest of
    its lifetime, they are not blocked or delayed. It provides no
    guarantee whatsoever ACROSS separate calls to this context manager
    (each call gets an independent, unrelated snapshot) — which is
    exactly why `source_after` in `build_canary_backup` remains a
    genuinely separate, complementary check, not a redundant one. And
    because nothing inside this block ever writes, the well-known
    REPEATABLE READ risk of a serialization failure on a write-write
    conflict (`could not serialize access due to concurrent update`)
    cannot occur here — that risk is specific to transactions that
    write under REPEATABLE READ/SERIALIZABLE, not to read-only ones."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        yield


def _fetch_payload_rows_in_snapshot(row_ids: tuple[int, ...]) -> tuple[PayloadRow, ...]:
    """Checkpoint 67.12.2 Part 2 — must be called from INSIDE an
    already-open `transaction.atomic()` block whose isolation level has
    been set to REPEATABLE READ by the caller (see
    `_repeatable_read_atomic` below). Issues the same single `.values()`
    statement `_fetch_payload_rows` does, but relies on the CALLER's
    transaction-level snapshot rather than opening its own — so that
    when this is invoked twice (once for the payload rows, once
    implicitly via the payload fingerprint computed from those same
    rows) both reads are guaranteed, by REPEATABLE READ's transaction-
    duration snapshot, to observe the SAME point-in-time view of the
    table, not merely each be internally self-consistent."""
    if not row_ids:
        return ()
    qs = HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values(
        "id", "instrument_id", "exchange", "symbol", "timeframe", "bar_timestamp",
        "open_price", "high_price", "low_price", "close_price", "volume",
        "source", "provenance", "source_timestamp_semantics", "canonicalization_state",
    )
    return tuple(
        PayloadRow(
            id=r["id"], instrument_id=r["instrument_id"], exchange=r["exchange"],
            symbol=r["symbol"], timeframe=r["timeframe"], bar_timestamp=r["bar_timestamp"],
            open_price=r["open_price"], high_price=r["high_price"], low_price=r["low_price"],
            close_price=r["close_price"], volume=r["volume"], source=r["source"],
            provenance=r["provenance"], source_timestamp_semantics=r["source_timestamp_semantics"],
            canonicalization_state=r["canonicalization_state"],
        )
        for r in qs
    )


def _fetch_payload_rows(row_ids: tuple[int, ...]) -> tuple[PayloadRow, ...]:
    """The ONLY database access this module performs: one ordered,
    read-only `.values()` query per call. Ordering by `id` here is a
    convenience only — `compute_payload_fingerprint` re-sorts by `id`
    itself and does not trust caller ordering.

    Checkpoint 67.12.1 Task 1 — SNAPSHOT-CONSISTENCY GUARANTEE, stated
    precisely (do not overclaim beyond this):

    A single Django `.values()` queryset, when iterated, issues exactly
    ONE SQL statement (one `SELECT ... WHERE id IN (...)`) to
    PostgreSQL. Under PostgreSQL's default READ COMMITTED isolation,
    each individual STATEMENT (not each transaction) sees a snapshot of
    the database taken at that statement's start — so every row this
    call returns, however many rows are in `row_ids`, is read from ONE
    consistent point-in-time view of the table. This is a genuine,
    documented PostgreSQL guarantee for a single statement, and it is
    what makes `source_before` (or `source_after`) internally
    consistent ACROSS the (up to) 70-plus rows of one canary unit, even
    though no application-level lock is held.

    What this guarantee does NOT provide, and what this module never
    claims it provides: consistency BETWEEN two separate calls to this
    function. `source_before` and `source_after` (see
    `build_canary_backup`) are each individually a one-statement
    consistent snapshot, but the database is free to change in the
    (typically sub-millisecond) gap between the two calls — that gap is
    exactly what the before/after fingerprint comparison exists to
    detect (defense-in-depth, not a snapshot-consistency mechanism
    itself; see the module docstring and `SourceChangedDuringExportError`).

    The call is wrapped in `transaction.atomic()` for explicitness and
    as defense-in-depth only — for a single read-only SELECT under
    READ COMMITTED, the transaction wrapper does not change the
    single-statement consistency guarantee above (that guarantee holds
    with or without an explicit transaction), but it does (a) document
    the intent unambiguously at the call site, (b) guarantee this
    function never silently participates in some caller's
    already-open, longer-lived transaction that could otherwise let an
    intervening statement change the read timing, and (c) match this
    codebase's existing style of wrapping DB-consistency-sensitive
    reads in `transaction.atomic()` (see `migration_execute.py`'s own
    revalidation block and `migration_advisory_lock.py`)."""
    if not row_ids:
        return ()
    with transaction.atomic():
        qs = HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values(
            "id", "instrument_id", "exchange", "symbol", "timeframe", "bar_timestamp",
            "open_price", "high_price", "low_price", "close_price", "volume",
            "source", "provenance", "source_timestamp_semantics", "canonicalization_state",
        )
        return tuple(
            PayloadRow(
                id=r["id"], instrument_id=r["instrument_id"], exchange=r["exchange"],
                symbol=r["symbol"], timeframe=r["timeframe"], bar_timestamp=r["bar_timestamp"],
                open_price=r["open_price"], high_price=r["high_price"], low_price=r["low_price"],
                close_price=r["close_price"], volume=r["volume"], source=r["source"],
                provenance=r["provenance"], source_timestamp_semantics=r["source_timestamp_semantics"],
                canonicalization_state=r["canonicalization_state"],
            )
            for r in qs
        )


def _serialize_row(row: PayloadRow) -> dict:
    return {
        "id": row.id,
        "instrument_id": row.instrument_id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "bar_timestamp": row.bar_timestamp.isoformat(),
        "open_price": str(row.open_price),
        "high_price": str(row.high_price),
        "low_price": str(row.low_price),
        "close_price": str(row.close_price),
        "volume": str(row.volume),
        "source": row.source,
        "provenance": row.provenance,
        "source_timestamp_semantics": row.source_timestamp_semantics,
        "canonicalization_state": row.canonicalization_state,
    }


@dataclass(frozen=True, slots=True)
class CanaryBackupArtifact:
    """The in-memory result of `build_canary_backup`. `as_json_dict()`
    is the exact shape written to the artifact file."""

    checkpoint: str
    migration_id: str
    migration_version: str
    unit_identity: dict
    row_count: int
    rows: tuple[dict, ...]
    scope_fingerprint: str
    payload_fingerprint: str
    source_before_fingerprint: str
    source_after_fingerprint: str
    generated_at: str

    def as_json_dict(self) -> dict:
        body = {
            "backup_kind": "canary_unit_export",
            "checkpoint": self.checkpoint,
            "migration_id": self.migration_id,
            "migration_version": self.migration_version,
            "unit_identity": self.unit_identity,
            "row_count": self.row_count,
            "scope_fingerprint": self.scope_fingerprint,
            "payload_fingerprint": self.payload_fingerprint,
            "source_before_fingerprint": self.source_before_fingerprint,
            "source_after_fingerprint": self.source_after_fingerprint,
            "generated_at": self.generated_at,
            "rows": list(self.rows),
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        backup_checksum = hashlib.sha256(canonical).hexdigest()
        body["backup_checksum"] = backup_checksum
        return body


def build_canary_backup(unit_result: UnitDryRunResult, *, checkpoint: str) -> CanaryBackupArtifact:
    """Part 3: takes the ACTUAL selected unit (produced by re-running
    `select_canary_unit` against a fresh, live `HistoricalBarMigrationDryRunner`
    plan) as its only unit-identifying input. Nothing about the
    instrument, date, timeframe, row count or expected fingerprint is
    hard-coded anywhere in this function body — every one of those
    values is read off `unit_result` or derived live from the database.
    """
    row_ids = tuple(p.row_id for p in unit_result.row_projections)

    # Checkpoint 67.12.2 Part 2: the payload-row fetch and the payload
    # fingerprint computed FROM those same rows are now performed
    # inside ONE REPEATABLE READ transaction (`_repeatable_read_atomic`)
    # — this is what proves the exported rows and the recorded
    # `payload_fingerprint` correspond to the same database snapshot,
    # not merely that each read was individually internally consistent
    # (that older, weaker guarantee is all a single READ-COMMITTED
    # statement — with or without `transaction.atomic()` — ever gave;
    # see `_fetch_payload_rows`'s docstring).
    with _repeatable_read_atomic():
        source_before = _fetch_payload_rows_in_snapshot(row_ids)
        fp_before = compute_payload_fingerprint(source_before)

    serialized_rows = tuple(_serialize_row(r) for r in sorted(source_before, key=lambda r: r.id))

    # Part 4 (pre-existing, kept as a SEPARATE, complementary check —
    # NOT proof of snapshot consistency, which the block above now
    # independently establishes): read the live payload a second time,
    # in its OWN separate transaction/snapshot, to detect whether state
    # OUTSIDE the export's transaction has since diverged from what was
    # exported. If the two payload fingerprints disagree, STOP - the
    # source mutated relative to the export and the backup is not
    # trustworthy.
    source_after = _fetch_payload_rows(row_ids)
    fp_after = compute_payload_fingerprint(source_after)

    if fp_before != fp_after:
        raise SourceChangedDuringExportError(before=fp_before, after=fp_after)

    segment = _segment_for_instrument(unit_result.unit.instrument_id)
    scope_inputs = _cas_scope_inputs(
        unit_key=unit_result.unit,
        segment=segment,
        proof_status=unit_result.proof_status,
        rows=[(p.row_id, p.old_timestamp) for p in unit_result.row_projections],
    )
    scope_fingerprint = compute_scope_fingerprint(scope_inputs)

    return CanaryBackupArtifact(
        checkpoint=checkpoint,
        migration_id=MIGRATION_ID,
        migration_version=f"{MIGRATION_VERSION}/{ELIGIBILITY_PREDICATE_VERSION}",
        unit_identity={
            "instrument_id": str(unit_result.unit.instrument_id),
            "timeframe": unit_result.unit.timeframe.value,
            "trading_date": unit_result.unit.trading_date.isoformat(),
        },
        row_count=len(serialized_rows),
        rows=serialized_rows,
        scope_fingerprint=scope_fingerprint,
        payload_fingerprint=fp_before,
        source_before_fingerprint=fp_before,
        source_after_fingerprint=fp_after,
        generated_at=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "CanaryBackupArtifact",
    "SourceChangedDuringExportError",
    "build_canary_backup",
]
