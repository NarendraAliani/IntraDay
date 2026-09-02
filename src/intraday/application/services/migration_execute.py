# File: src/intraday/application/services/migration_execute.py
#
# Checkpoint 67.10 — the EXECUTABLE (write-CAPABLE) migration runner.
#
# This module is the sibling of `migration_dry_run.py` that is actually
# capable of issuing a real `UPDATE` against `HistoricalBar` and
# writing real `MigrationRun`/`MigrationUnit`/`MigrationRow` audit
# rows. It is invoked ONLY by the new `migration_67_10 --execute`
# management command, and ONLY against Django's disposable pytest test
# database inside this checkpoint's own test suite — see that
# command's module docstring and `tests/unit/application/services/
# test_migration_67_10_execute.py` for the zero-production-writes
# proof.
#
# REUSE, NOT REIMPLEMENTATION (the directive's explicit requirement):
# every eligibility/collision/proof-scope computation below is
# performed by constructing a `HistoricalBarMigrationDryRunner`
# (67.7's read-only runner, completely unmodified) and calling its
# EXISTING `_evaluate_unit` / `_live_eligible_rows` methods — the same
# methods `--dry-run` itself calls. This module adds exactly three new
# things on top of that reused evaluation: (1) a real advisory-lock
# acquisition in canonical order (2) a real transaction with a real
# descending-order `UPDATE` (3) real audit-row persistence — nothing
# about how a unit is judged SAFE/UNSAFE is duplicated or re-derived
# here.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, connection, transaction
from django.utils import timezone as django_timezone

from intraday.application.services.migration_advisory_lock import historical_migration_lock_key
from intraday.application.services.migration_dry_run import (
    MIGRATION_ID,
    HistoricalBarMigrationDryRunner,
    MigrationUnitKey,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_scope_fingerprint import (
    MigrationScopeInputs,
    ScopeFingerprintMismatch,
    compute_scope_fingerprint,
    require_scope_fingerprint_unchanged,
)
from intraday.domain.market_data.migration_state import (
    MigrationRunState,
    MigrationUnitState,
    is_legal_run_transition,
)
from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_CANONICALIZED
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar, MigrationRow, MigrationRun, MigrationUnit

MIGRATION_VERSION = "67.10"
ELIGIBILITY_PREDICATE_VERSION = "67.7-cas-5m-nse-open-uncanonicalized-v1"


class ProductionWriteGuardError(RuntimeError):
    """Raised (never silently swallowed) if `--execute` is ever pointed
    at a database connection whose name does not look like a Django
    disposable test database. Django prefixes the configured DB name
    with `test_` when it creates the per-run pytest/CI test database
    (unless a project explicitly overrides `TEST['NAME']`, which this
    project does not) — checking that prefix is a cheap, real signal
    that fails loudly instead of trusting caller discipline alone."""


def assert_write_capable_connection_is_test_database() -> None:
    db_name = str(connection.settings_dict.get("NAME", ""))
    if not db_name.startswith("test_"):
        raise ProductionWriteGuardError(
            f"migration_execute refuses to run: connection {connection.alias!r} points at "
            f"database {db_name!r}, which does not look like a Django disposable test "
            "database (expected a 'test_' prefixed name). This checkpoint must NEVER write "
            "to a non-test database."
        )


class ExecuteOutcome(enum.Enum):
    COMMITTED = "COMMITTED"
    STOPPED_REVALIDATION_MISMATCH = "STOPPED_REVALIDATION_MISMATCH"
    REFUSED_UNSAFE = "REFUSED_UNSAFE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class UnitExecutionResult:
    unit: MigrationUnitKey
    outcome: ExecuteOutcome
    final_state: MigrationUnitState
    row_count: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MigrationExecuteReport:
    run_id: str
    run_state: MigrationRunState
    requested_unit_count: int
    committed_unit_count: int
    stopped_unit_count: int
    refused_unit_count: int
    failed_unit_count: int
    units: tuple[UnitExecutionResult, ...]


def _cas_scope_inputs(
    *, unit_key: MigrationUnitKey, segment: str, proof_status: str, rows: list[tuple[int, datetime]]
) -> MigrationScopeInputs:
    return MigrationScopeInputs(
        migration_version=MIGRATION_VERSION,
        provider="REAL_DHAN",
        segment=segment,
        timeframe=unit_key.timeframe.value,
        era="CAS_ERA",
        eligibility_predicate_version=ELIGIBILITY_PREDICATE_VERSION,
        eligible_row_ids=tuple(r[0] for r in rows),
        old_timestamps_by_row_id=tuple((r[0], r[1]) for r in rows),
        proof_scope=proof_status,
    )


@dataclass(frozen=True, slots=True)
class HistoricalBarMigrationExecutor:
    """Write-capable. MUST only ever be constructed against a
    connection that `assert_write_capable_connection_is_test_database`
    accepts — the executor calls that guard itself, first thing,
    inside `run()`, so even a caller that forgets to check is still
    protected."""

    dry_runner: HistoricalBarMigrationDryRunner

    def run(
        self,
        *,
        unit_filter: frozenset[MigrationUnitKey] | None = None,
        limit: int | None = None,
    ) -> MigrationExecuteReport:
        assert_write_capable_connection_is_test_database()

        # Step 1 - PLANNING pass: reuse the exact same read-only
        # enumeration/evaluation the dry-run path uses. This produces,
        # per unit, the SAFE/unsafe verdict and the row set the scope
        # fingerprint below is computed from.
        plan = self.dry_runner.run()

        target_units = [
            u for u in plan.units
            if unit_filter is None or u.unit in unit_filter
        ]
        if limit is not None:
            target_units = target_units[:limit]

        run_state = MigrationRunState.PLANNED
        results: list[UnitExecutionResult] = []

        if target_units:
            self._ensure_run_row(run_state)
            run_state = self._transition_run(run_state, MigrationRunState.RUNNING)

        for unit_result in target_units:
            results.append(self._execute_unit(unit_result))

        committed = sum(1 for r in results if r.outcome is ExecuteOutcome.COMMITTED)
        stopped = sum(1 for r in results if r.outcome is ExecuteOutcome.STOPPED_REVALIDATION_MISMATCH)
        refused = sum(1 for r in results if r.outcome is ExecuteOutcome.REFUSED_UNSAFE)
        failed = sum(1 for r in results if r.outcome is ExecuteOutcome.FAILED)

        if target_units:
            if committed == len(results):
                run_state = self._transition_run(run_state, MigrationRunState.COMPLETED)
            elif committed > 0:
                run_state = self._transition_run(run_state, MigrationRunState.PARTIALLY_COMPLETED)
            else:
                run_state = self._transition_run(run_state, MigrationRunState.ABORTED)

        return MigrationExecuteReport(
            run_id=MIGRATION_ID,
            run_state=run_state,
            requested_unit_count=len(target_units),
            committed_unit_count=committed,
            stopped_unit_count=stopped,
            refused_unit_count=refused,
            failed_unit_count=failed,
            units=tuple(results),
        )

    # -- run-row bookkeeping -----------------------------------------------
    def _ensure_run_row(self, state: MigrationRunState) -> None:
        MigrationRun.objects.get_or_create(
            migration_id=MIGRATION_ID,
            defaults={
                "migration_version": MIGRATION_VERSION,
                "status": state.value,
                "scope_fingerprint": "",
                "started_at": django_timezone.now(),
            },
        )

    def _transition_run(self, current: MigrationRunState, target: MigrationRunState) -> MigrationRunState:
        if not is_legal_run_transition(current, target):
            raise AssertionError(f"illegal run transition {current!r} -> {target!r}")
        update_fields = {"status": target.value}
        if target in (MigrationRunState.COMPLETED, MigrationRunState.ABORTED):
            update_fields["completed_at"] = django_timezone.now()
        MigrationRun.objects.filter(migration_id=MIGRATION_ID).update(**update_fields)
        return target

    # -- per-unit execution --------------------------------------------------
    def _execute_unit(self, planned_unit) -> UnitExecutionResult:
        unit_key = planned_unit.unit

        # A unit the PLANNING pass already judged unsafe (wrong
        # segment/era, already canonical, out-of-scope collision, ...)
        # is refused before ANY lock or transaction is opened - never
        # attempt a write against something the reused evaluation
        # already rejected.
        if planned_unit.state is not MigrationUnitState.DRY_RUN_SAFE:
            self._write_unit_audit(
                unit_key, MigrationUnitState.FAILED, planned_unit.row_count,
                error_code="REFUSED_UNSAFE_AT_PLANNING",
            )
            return UnitExecutionResult(
                unit=unit_key, outcome=ExecuteOutcome.REFUSED_UNSAFE,
                final_state=MigrationUnitState.FAILED, row_count=planned_unit.row_count,
                reasons=planned_unit.unsafe_reasons,
            )

        # Snapshot fingerprint from the PLANNING pass - what this unit
        # is entitled to touch, computed before any lock was held.
        planned_old_ts = tuple(
            (rp.row_id, rp.old_timestamp) for rp in planned_unit.row_projections
        )
        from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
            _segment_for_instrument,
        )
        segment = _segment_for_instrument(unit_key.instrument_id)
        expected_fingerprint = compute_scope_fingerprint(
            _cas_scope_inputs(
                unit_key=unit_key, segment=segment, proof_status=planned_unit.proof_status,
                rows=list(planned_old_ts),
            )
        )

        try:
            with transaction.atomic():
                lock_key = historical_migration_lock_key(unit_key.instrument_id, unit_key.timeframe)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])

                # Step 2 - REVALIDATION: re-run the SAME reused
                # evaluation logic now that the lock is held, against
                # whatever is live in the DB right now.
                fresh_rows = self._current_rows_for_unit(unit_key)
                revalidated = self.dry_runner._evaluate_unit(unit_key, fresh_rows)

                if revalidated.state is not MigrationUnitState.DRY_RUN_SAFE:
                    raise ScopeFingerprintMismatch(
                        expected=expected_fingerprint, actual="<revalidation-unsafe>",
                        unit_id=self._unit_id(unit_key),
                    )

                revalidated_old_ts = tuple(
                    (rp.row_id, rp.old_timestamp) for rp in revalidated.row_projections
                )
                recomputed_fingerprint = compute_scope_fingerprint(
                    _cas_scope_inputs(
                        unit_key=unit_key, segment=segment, proof_status=revalidated.proof_status,
                        rows=list(revalidated_old_ts),
                    )
                )
                require_scope_fingerprint_unchanged(
                    expected=expected_fingerprint, recomputed=recomputed_fingerprint,
                    unit_id=self._unit_id(unit_key),
                )

                # Step 3 - APPLY: descending bar_timestamp order,
                # exactly the SQL pattern proven safe in 67.8's
                # disposable-DB trial.
                ordered_desc = sorted(
                    revalidated.row_projections, key=lambda rp: rp.old_timestamp, reverse=True
                )
                for rp in ordered_desc:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE persistence_historicalbar
                            SET bar_timestamp = %s, canonicalization_state = %s
                            WHERE id = %s
                            """,
                            [rp.new_timestamp, CANONICALIZATION_STATE_CANONICALIZED, rp.row_id],
                        )

                # Step 4 - VERIFY postconditions.
                self._verify_postconditions(unit_key, revalidated.row_projections)

                # Step 5 - AUDIT rows, inside the same transaction so a
                # later rollback undoes them together with the data
                # write (no orphaned "COMMITTED" audit row for data
                # that never actually committed).
                self._write_row_audit(revalidated.row_projections)
                self._write_unit_audit(
                    unit_key, MigrationUnitState.COMMITTED, len(revalidated.row_projections),
                    error_code="",
                )
        except ScopeFingerprintMismatch as exc:
            self._write_unit_audit(
                unit_key, MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
                planned_unit.row_count, error_code=str(exc)[:64],
            )
            return UnitExecutionResult(
                unit=unit_key, outcome=ExecuteOutcome.STOPPED_REVALIDATION_MISMATCH,
                final_state=MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
                row_count=planned_unit.row_count, reasons=(str(exc),),
            )
        except (IntegrityError, AssertionError) as exc:
            self._write_unit_audit(
                unit_key, MigrationUnitState.FAILED, planned_unit.row_count,
                error_code=str(exc)[:64],
            )
            return UnitExecutionResult(
                unit=unit_key, outcome=ExecuteOutcome.FAILED,
                final_state=MigrationUnitState.FAILED, row_count=planned_unit.row_count,
                reasons=(str(exc),),
            )

        return UnitExecutionResult(
            unit=unit_key, outcome=ExecuteOutcome.COMMITTED,
            final_state=MigrationUnitState.COMMITTED,
            row_count=len(planned_unit.row_projections), reasons=(),
        )

    def _current_rows_for_unit(
        self, unit_key: MigrationUnitKey
    ) -> list[tuple[int, InstrumentId, datetime]]:
        all_eligible = self.dry_runner._live_eligible_rows()
        out: list[tuple[int, InstrumentId, datetime]] = []
        for row_id, instrument_id_str, bar_ts in all_eligible:
            instrument_id = make_instrument_id(Exchange("NSE"), instrument_id_str.split(":")[-1])
            if instrument_id != unit_key.instrument_id:
                continue
            from intraday.domain.session.calendar import INDIA_STANDARD_TIME
            if bar_ts.astimezone(INDIA_STANDARD_TIME).date() != unit_key.trading_date:
                continue
            out.append((row_id, instrument_id, bar_ts))
        return out

    def _verify_postconditions(self, unit_key: MigrationUnitKey, projections) -> None:
        expected_new_ts = {rp.new_timestamp for rp in projections}
        actual_rows = list(
            HistoricalBar.objects.filter(id__in=[rp.row_id for rp in projections]).values_list(
                "id", "bar_timestamp", "canonicalization_state"
            )
        )
        if len(actual_rows) != len(projections):
            raise AssertionError(
                f"postcondition row-count mismatch for unit {unit_key}: expected "
                f"{len(projections)}, found {len(actual_rows)}"
            )
        actual_new_ts = {ts for _id, ts, _state in actual_rows}
        if actual_new_ts != expected_new_ts:
            raise AssertionError(
                f"postcondition timestamp-set mismatch for unit {unit_key}: expected "
                f"{sorted(expected_new_ts)}, found {sorted(actual_new_ts)}"
            )
        if any(state != CANONICALIZATION_STATE_CANONICALIZED for _id, _ts, state in actual_rows):
            raise AssertionError(f"postcondition canonicalization_state mismatch for unit {unit_key}")
        if len(actual_new_ts) != len(projections):
            raise AssertionError(f"postcondition uniqueness violated for unit {unit_key}")

    def _unit_id(self, unit_key: MigrationUnitKey) -> str:
        return f"{unit_key.instrument_id}|{unit_key.timeframe.value}|{unit_key.trading_date.isoformat()}"

    def _write_row_audit(self, projections) -> None:
        records = [
            MigrationRow(
                migration_id=MIGRATION_ID,
                row_id=rp.row_id,
                old_timestamp=rp.old_timestamp,
                new_timestamp=rp.new_timestamp,
                source_semantics="OPEN",
                proof_scope="PROVEN",
                status=MigrationUnitState.COMMITTED.value,
            )
            for rp in projections
        ]
        seen: set[tuple[str, int]] = set()
        for r in records:
            key = (r.migration_id, r.row_id)
            if key in seen:
                raise AssertionError(f"duplicate (migration_id, row_id) audit key: {key}")
            seen.add(key)
        MigrationRow.objects.bulk_create(records)

    def _write_unit_audit(
        self, unit_key: MigrationUnitKey, state: MigrationUnitState, row_count: int, *, error_code: str
    ) -> None:
        MigrationUnit.objects.update_or_create(
            migration_id=MIGRATION_ID,
            unit_id=self._unit_id(unit_key),
            defaults={
                "instrument_id": str(unit_key.instrument_id),
                "timeframe": unit_key.timeframe.value,
                "trading_date": unit_key.trading_date,
                "status": state.value,
                "old_row_count": row_count,
                "new_row_count": row_count if state is MigrationUnitState.COMMITTED else 0,
                "old_scope_fingerprint": "",
                "committed_at": django_timezone.now() if state is MigrationUnitState.COMMITTED else None,
                "error_code": error_code,
            },
        )


# ---------------------------------------------------------------------
# Checkpoint 67.11.5 Part 1/2/3 — PRODUCTION resume/reconciliation.
#
# This is the exact logic 67.11 proved inside
# `test_migration_67_11_stress.py` (`reconcile_abandoned_unit` /
# `resume_migration_run`), extracted verbatim (no new retry semantics
# invented) into the real application layer so it is importable
# production code, not test-local logic. The test file is updated to
# import these two functions from here instead of defining its own
# copies — see Part 1 of taskReport.md for the before/after proof.
#
# PART 3 — abandoned-run detection design decision (see taskReport.md
# for the full argument): NO heartbeat/lease table is introduced. The
# existing `MigrationUnit` control-plane row (present or absent) plus
# a live read of `HistoricalBar.canonicalization_state` for that unit's
# rows is durable DATABASE state, already sufficient to classify any
# unit as UNMODIFIED / FULLY_MIGRATED / INCONSISTENT with zero
# dependency on process memory, wall-clock timestamps, or a live
# heartbeat — because a real Postgres transaction (proven by the Part 4
# crash matrix, 67.11) guarantees only two reachable live states for a
# unit whose write was interrupted: fully rolled back, or fully
# committed. A heartbeat/lease would add a new failure mode (a stale
# lease, a clock skew) to answer a question the existing state model
# already answers exactly — so, per the directive's explicit
# instruction not to over-engineer, none is added here.
from datetime import date as _date


def reconcile_abandoned_unit(
    *, instrument_id: InstrumentId, timeframe: Timeframe, trading_date: _date, migration_id: str
) -> str:
    """Given a unit whose `MigrationUnit` audit row is absent or stale,
    inspect the ACTUAL live `HistoricalBar` state for this unit and
    classify it. Returns one of 'UNMODIFIED' / 'FULLY_MIGRATED' /
    'INCONSISTENT' — never guesses; 'INCONSISTENT' means the caller
    must STOP. See module docstring above (Part 3) for why this is
    sufficient without a heartbeat/lease mechanism."""
    from intraday.domain.session.calendar import INDIA_STANDARD_TIME
    from datetime import UTC as _UTC, datetime as _datetime

    day_start_utc = _datetime.combine(trading_date, _datetime.min.time()).replace(
        tzinfo=INDIA_STANDARD_TIME
    ).astimezone(_UTC)
    day_end_utc = _datetime.combine(trading_date, _datetime.max.time()).replace(
        tzinfo=INDIA_STANDARD_TIME
    ).astimezone(_UTC)
    rows = list(
        HistoricalBar.objects.filter(
            instrument_id=str(instrument_id), timeframe=timeframe.value,
            bar_timestamp__gte=day_start_utc, bar_timestamp__lte=day_end_utc,
        ).values_list("canonicalization_state", flat=True)
    )
    if not rows:
        return "INCONSISTENT"  # no live rows at all for a unit believed migratable - STOP
    states = set(rows)
    if states == {"UNCANONICALIZED"}:
        return "UNMODIFIED"
    if states == {"CANONICALIZED"}:
        return "FULLY_MIGRATED"
    return "INCONSISTENT"  # mixed states within one unit - never guess, STOP


def resume_migration_run(
    *, executor: "HistoricalBarMigrationExecutor", migration_id: str,
    candidate_units: frozenset[MigrationUnitKey],
) -> MigrationExecuteReport | None:
    """PRODUCTION resume engine on top of the EXISTING executor (no
    second migration engine): loads whatever `MigrationUnit` rows
    already exist for `migration_id`, NEVER re-targets a `COMMITTED`
    unit (hard rule — filtered out before `executor.run()` is even
    called), reconciles any unit that looks abandoned/incomplete via
    `reconcile_abandoned_unit` and STOPS (raises) on an INCONSISTENT
    verdict rather than resuming through it, and then calls the real
    `executor.run()` (itself doing its own fresh eligibility +
    scope-fingerprint revalidation per unit) only for the remaining
    safe candidates. Returns the executor's own report for whatever
    subset was actually resumed, or `None` if nothing was resumable."""
    already_committed_ids = set(
        MigrationUnit.objects.filter(
            migration_id=migration_id, status=MigrationUnitState.COMMITTED.value
        ).values_list("unit_id", flat=True)
    )

    def _unit_id(u: MigrationUnitKey) -> str:
        return f"{u.instrument_id}|{u.timeframe.value}|{u.trading_date.isoformat()}"

    resumable: set[MigrationUnitKey] = set()
    for unit_key in candidate_units:
        if _unit_id(unit_key) in already_committed_ids:
            continue  # COMMITTED unit -> NEVER migrate again
        verdict = reconcile_abandoned_unit(
            instrument_id=unit_key.instrument_id, timeframe=unit_key.timeframe,
            trading_date=unit_key.trading_date, migration_id=migration_id,
        )
        if verdict == "INCONSISTENT":
            raise RuntimeError(
                f"resume refuses to proceed: unit {_unit_id(unit_key)} is in an "
                "INCONSISTENT state (DB state does not cleanly match either 'unmodified' "
                "or 'fully migrated') - STOPPING, not guessing"
            )
        if verdict == "FULLY_MIGRATED":
            continue  # already migrated at the data-plane level; skip explicitly so no
            # lock is even attempted for a done unit.
        resumable.add(unit_key)

    if not resumable:
        return None
    return executor.run(unit_filter=frozenset(resumable))


__all__ = [
    "MIGRATION_VERSION",
    "ELIGIBILITY_PREDICATE_VERSION",
    "ProductionWriteGuardError",
    "assert_write_capable_connection_is_test_database",
    "ExecuteOutcome",
    "UnitExecutionResult",
    "MigrationExecuteReport",
    "HistoricalBarMigrationExecutor",
    "reconcile_abandoned_unit",
    "resume_migration_run",
]
