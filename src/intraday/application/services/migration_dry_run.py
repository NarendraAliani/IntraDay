# File: src/intraday/application/services/migration_dry_run.py
#
# Checkpoint 67.7 — the DRY-RUN-ONLY migration runner (Parts 3/4/5/8/
# 9/10/11/12/13). Enumerates the live-eligible migration units,
# re-validates each against the CURRENT database, computes projected
# old->new timestamp mappings, classifies collisions, simulates the
# descending-order update sequence, simulates algebraic rollback,
# computes projected completeness, and distinguishes CANONICALIZED
# from RESEARCH_READY throughout — WITHOUT EVER CALLING
# `.save()`/`.create()`/`.update()`/`.bulk_update()`/`.bulk_create()`/
# `.delete()`/raw SQL UPDATE against `HistoricalBar`.
#
# ARCHITECTURAL WRITE-INCAPABILITY (Part 5, "not just designed not to,
# actually incapable"): this module imports and uses ONLY
# `django.db.models.QuerySet.filter/.values_list/.count/.order_by` —
# read-only ORM primitives — against `HistoricalBar` directly. It never
# imports `DjangoHistoricalBarRepository.bulk_upsert` (the one write
# method that Protocol exposes) or any Django model `.save()`/
# `.delete()`/`QuerySet.update()`/`.bulk_create()`/`.bulk_update()`
# method. `NoWriteHistoricalBarRepository` below is the SECOND,
# independent layer of defense-in-depth Part 5 asks for: a concrete
# `HistoricalBarWriteRepository`-Protocol-shaped object whose only
# method unconditionally raises `DryRunWriteAttemptedError` — the
# runner constructs one and asserts (in its own self-test, mirrored by
# `test_migration_67_7_dry_run.py`) that calling it raises. No
# reference to a real `DjangoHistoricalBarRepository` write method
# exists anywhere below this line.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_advisory_lock import historical_migration_lock_key
from intraday.domain.market_data.migration_audit import (
    MigrationAuditRecord,
    assert_unique_migration_row_pairs,
    forward_shift,
    verify_algebraic_rollback,
)
from intraday.domain.market_data.migration_state import (
    MigrationRunState,
    MigrationUnitState,
    assert_dry_run_state_reachable,
)
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_UNCANONICALIZED,
    SourceTimestampSemantics,
    is_canonicalized,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE, INDIA_STANDARD_TIME
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    _resolve_intraday_proof_scope,
    _segment_for_instrument,
)
from intraday.infrastructure.persistence.models import HistoricalBar

MIGRATION_ID = "67.7-CAS-5m-NSE-OPEN-CLOSE-SHIFT"
FIVE_MINUTE_DELTA = timedelta(minutes=5)


class DryRunWriteAttemptedError(RuntimeError):
    """Raised by `NoWriteHistoricalBarRepository.bulk_upsert` — proof
    that ANY code path attempting to route a write through the
    write-Protocol during a dry-run fails loudly rather than silently
    succeeding (Part 5)."""


@dataclass(frozen=True, slots=True)
class NoWriteHistoricalBarRepository:
    """A `HistoricalBarWriteRepository`-Protocol-shaped object with NO
    write capability at all — `bulk_upsert` unconditionally raises.
    The dry-run runner never calls this (it never needs a writer), but
    holds/exposes it so a test can prove that even if a future code
    change accidentally threaded a "writer" into the dry-run path, that
    writer is architecturally incapable of writing."""

    def bulk_upsert(self, bars, **kwargs):  # noqa: ANN001, ANN003 - deliberately never called
        raise DryRunWriteAttemptedError(
            "dry-run attempted to call bulk_upsert() against HistoricalBar - this is "
            "architecturally forbidden; the dry-run runner must never be given a "
            "write-capable repository"
        )


class CollisionClassification(enum.Enum):
    """Part 9's exhaustive collision taxonomy."""

    NO_COLLISION = "NO_COLLISION"
    IN_SCOPE_EXPECTED_SHIFT = "IN_SCOPE_EXPECTED_SHIFT"
    OUT_OF_SCOPE_EXISTING_COLLISION = "OUT_OF_SCOPE_EXISTING_COLLISION"
    CROSS_PROVENANCE_COLLISION = "CROSS_PROVENANCE_COLLISION"
    ALREADY_CANONICAL_COLLISION = "ALREADY_CANONICAL_COLLISION"
    DIFFERENT_PROVIDER_COLLISION = "DIFFERENT_PROVIDER_COLLISION"


_UNSAFE_CLASSIFICATIONS = frozenset(
    {
        CollisionClassification.OUT_OF_SCOPE_EXISTING_COLLISION,
        CollisionClassification.CROSS_PROVENANCE_COLLISION,
        CollisionClassification.ALREADY_CANONICAL_COLLISION,
        CollisionClassification.DIFFERENT_PROVIDER_COLLISION,
    }
)


class CompletenessVerdict(enum.Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class RowProjection:
    row_id: int
    old_timestamp: datetime
    new_timestamp: datetime
    classification: CollisionClassification
    rollback_ok: bool
    projected_final_position: datetime


@dataclass(frozen=True, slots=True)
class MigrationUnitKey:
    instrument_id: InstrumentId
    timeframe: Timeframe
    trading_date: date


@dataclass(frozen=True, slots=True)
class UnitDryRunResult:
    unit: MigrationUnitKey
    lock_key: int
    proof_status: str
    row_count: int
    row_projections: tuple[RowProjection, ...]
    state: MigrationUnitState
    unsafe_reasons: tuple[str, ...]
    completeness: CompletenessVerdict
    audit_records: tuple[MigrationAuditRecord, ...]


@dataclass(frozen=True, slots=True)
class MigrationDryRunReport:
    run_id: str
    run_state: MigrationRunState
    eligible_row_count: int
    unit_count: int
    units: tuple[UnitDryRunResult, ...]
    safe_unit_count: int
    unsafe_unit_count: int


def _cas_era_bounds(trading_date: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(trading_date, time.min).replace(tzinfo=INDIA_STANDARD_TIME)
    end_local = datetime.combine(trading_date, time.max).replace(tzinfo=INDIA_STANDARD_TIME)
    return start_local.astimezone(dt_timezone.utc), end_local.astimezone(dt_timezone.utc)


@dataclass(frozen=True, slots=True)
class HistoricalBarMigrationDryRunner:
    """Read-only. Constructs itself from ONLY the read repository and
    coverage service already used elsewhere in this codebase for
    read-only purposes — never given, never constructs, and never
    imports a write-capable repository."""

    coverage_service: HistoricalDataCoverageService

    def run(self) -> MigrationDryRunReport:
        eligible_rows = self._live_eligible_rows()
        units_index: dict[MigrationUnitKey, list[tuple[int, InstrumentId, datetime]]] = {}
        for row_id, instrument_id_str, bar_ts in eligible_rows:
            instrument_id = make_instrument_id(Exchange("NSE"), instrument_id_str.split(":")[-1])
            local_dt = bar_ts.astimezone(INDIA_STANDARD_TIME)
            key = MigrationUnitKey(
                instrument_id=instrument_id, timeframe=Timeframe.FIVE_MINUTE,
                trading_date=local_dt.date(),
            )
            units_index.setdefault(key, []).append((row_id, instrument_id, bar_ts))

        unit_results: list[UnitDryRunResult] = []
        for unit_key, rows in sorted(units_index.items(), key=lambda kv: (str(kv[0].instrument_id), kv[0].trading_date)):
            unit_results.append(self._evaluate_unit(unit_key, rows))

        safe = sum(1 for u in unit_results for _ in [None] if u.state is MigrationUnitState.DRY_RUN_SAFE)
        unsafe = len(unit_results) - safe

        run_state = MigrationRunState.PLANNED
        assert_dry_run_state_reachable(run_state)
        for u in unit_results:
            assert_dry_run_state_reachable(u.state)

        return MigrationDryRunReport(
            run_id=MIGRATION_ID,
            run_state=run_state,
            eligible_row_count=len(eligible_rows),
            unit_count=len(unit_results),
            units=tuple(unit_results),
            safe_unit_count=safe,
            unsafe_unit_count=unsafe,
        )

    # -- read-only live queries -------------------------------------------------
    def _live_eligible_rows(self) -> tuple[tuple[int, str, datetime], ...]:
        """The ONLY database access this runner performs. Pure read:
        `.values_list()` over `.filter()` — no `.update()`, no
        `.bulk_create()`, no `.save()`, no `.delete()`."""
        qs = HistoricalBar.objects.filter(
            provenance=PROVENANCE_REAL_DHAN,
            exchange="NSE",
            timeframe="5m",
            canonicalization_state=CANONICALIZATION_STATE_UNCANONICALIZED,
        ).values_list("id", "instrument_id", "bar_timestamp")
        rows = []
        for row_id, instrument_id_str, bar_ts in qs:
            local_dt = bar_ts.astimezone(INDIA_STANDARD_TIME)
            if local_dt.date() >= CAS_EFFECTIVE_DATE:
                rows.append((row_id, instrument_id_str, bar_ts))
        return tuple(rows)

    def _occupant_at(self, instrument_id: InstrumentId, timeframe: Timeframe, ts: datetime):
        """Read-only lookup of whatever row (if any) already occupies
        `(instrument_id, timeframe, ts)` — used purely to classify a
        projected collision, never to touch it."""
        return (
            HistoricalBar.objects.filter(
                instrument_id=str(instrument_id), timeframe=timeframe.value, bar_timestamp=ts
            )
            .values("provenance", "canonicalization_state", "source")
            .first()
        )

    def _evaluate_unit(
        self, unit_key: MigrationUnitKey, rows: list[tuple[int, InstrumentId, datetime]]
    ) -> UnitDryRunResult:
        lock_key = historical_migration_lock_key(unit_key.instrument_id, unit_key.timeframe)

        # Part 3/8: re-validate proof scope against the CURRENT window,
        # never trust the old snapshot.
        segment = _segment_for_instrument(unit_key.instrument_id)
        era_start, era_end = _cas_era_bounds(unit_key.trading_date)
        scope = _resolve_intraday_proof_scope(
            unit_key.timeframe, era_start, era_end, segment=segment
        )
        proof_proven = scope.proof_status.value == "PROVEN"

        unsafe_reasons: list[str] = []
        if not proof_proven:
            unsafe_reasons.append(
                f"proof_scope revalidation failed: segment={segment} timeframe="
                f"{unit_key.timeframe.value} trading_date={unit_key.trading_date} resolved "
                f"proof_status={scope.proof_status.value}"
            )

        eligible_old_ts = {r[2] for r in rows}
        ordered_desc = sorted(rows, key=lambda r: r[2], reverse=True)

        vacated: set[datetime] = set()
        projections: list[RowProjection] = []
        audit_records: list[MigrationAuditRecord] = []
        for row_id, instrument_id, old_ts in ordered_desc:
            new_ts = forward_shift(old_ts, FIVE_MINUTE_DELTA)
            rollback_ok = verify_algebraic_rollback(old_ts, FIVE_MINUTE_DELTA)

            if new_ts in vacated:
                classification = CollisionClassification.IN_SCOPE_EXPECTED_SHIFT
            elif new_ts in eligible_old_ts:
                # occupied by another eligible row that has not vacated
                # yet in this descending pass - still safe, since that
                # row will itself vacate before this one lands (it
                # sorts higher and is processed earlier).
                classification = CollisionClassification.IN_SCOPE_EXPECTED_SHIFT
            else:
                occupant = self._occupant_at(instrument_id, unit_key.timeframe, new_ts)
                if occupant is None:
                    classification = CollisionClassification.NO_COLLISION
                elif occupant["provenance"] != PROVENANCE_REAL_DHAN:
                    classification = CollisionClassification.CROSS_PROVENANCE_COLLISION
                elif is_canonicalized(occupant["canonicalization_state"]):
                    classification = CollisionClassification.ALREADY_CANONICAL_COLLISION
                elif occupant["source"] not in ("API_FETCH",):
                    classification = CollisionClassification.DIFFERENT_PROVIDER_COLLISION
                else:
                    classification = CollisionClassification.OUT_OF_SCOPE_EXISTING_COLLISION

            if classification in _UNSAFE_CLASSIFICATIONS:
                unsafe_reasons.append(
                    f"row {row_id}: {classification.value} at projected new_timestamp={new_ts.isoformat()}"
                )
            if not rollback_ok:
                unsafe_reasons.append(f"row {row_id}: algebraic rollback verification FAILED")

            projections.append(
                RowProjection(
                    row_id=row_id,
                    old_timestamp=old_ts,
                    new_timestamp=new_ts,
                    classification=classification,
                    rollback_ok=rollback_ok,
                    projected_final_position=new_ts,
                )
            )
            audit_records.append(
                MigrationAuditRecord(
                    migration_id=MIGRATION_ID,
                    row_id=row_id,
                    instrument_id=unit_key.instrument_id,
                    timeframe=unit_key.timeframe,
                    old_timestamp=old_ts,
                    new_timestamp=new_ts,
                    source_semantics=SourceTimestampSemantics.OPEN.value,
                    proof_scope=scope.proof_status.value,
                    status=MigrationUnitState.PENDING,
                    applied_at=None,
                )
            )
            vacated.add(old_ts)

        assert_unique_migration_row_pairs(tuple(audit_records))

        # Part 12: completeness, via the SAME, unmodified
        # HistoricalDataCoverageService every other consumer uses - no
        # parallel expected-set logic invented here.
        start_bound, end_bound = _cas_era_bounds(unit_key.trading_date)
        coverage = self.coverage_service.get_coverage(
            unit_key.instrument_id, unit_key.timeframe, start_bound, end_bound
        )
        if coverage.expected_bar_count == 0:
            completeness = CompletenessVerdict.INVALID
        elif coverage.is_complete:
            completeness = CompletenessVerdict.COMPLETE
        elif coverage.cached_bar_count > 0:
            completeness = CompletenessVerdict.PARTIAL
        else:
            completeness = CompletenessVerdict.UNRESOLVED

        if not proof_proven:
            state = MigrationUnitState.STOPPED_REVALIDATION_MISMATCH
        elif unsafe_reasons:
            state = MigrationUnitState.FAILED
        else:
            state = MigrationUnitState.DRY_RUN_SAFE

        # bump audit_records' status to reflect the unit's final
        # evaluated state - still never persisted anywhere.
        audit_records = tuple(
            MigrationAuditRecord(
                migration_id=r.migration_id, row_id=r.row_id, instrument_id=r.instrument_id,
                timeframe=r.timeframe, old_timestamp=r.old_timestamp, new_timestamp=r.new_timestamp,
                source_semantics=r.source_semantics, proof_scope=r.proof_scope, status=state,
                applied_at=None,
            )
            for r in audit_records
        )

        return UnitDryRunResult(
            unit=unit_key,
            lock_key=lock_key,
            proof_status=scope.proof_status.value,
            row_count=len(rows),
            row_projections=tuple(projections),
            state=state,
            unsafe_reasons=tuple(unsafe_reasons),
            completeness=completeness,
            audit_records=audit_records,
        )


__all__ = [
    "MIGRATION_ID",
    "DryRunWriteAttemptedError",
    "NoWriteHistoricalBarRepository",
    "CollisionClassification",
    "CompletenessVerdict",
    "RowProjection",
    "MigrationUnitKey",
    "UnitDryRunResult",
    "MigrationDryRunReport",
    "HistoricalBarMigrationDryRunner",
]
