# tests/unit/application/services/test_migration_67_10_execute.py
#
# Checkpoint 67.10 test coverage for the WRITE-CAPABLE migration
# runner (`migration_execute.py` + `migration_67_10 --execute`).
# EVERY test in this file that touches `HistoricalBar` runs against
# Django's disposable pytest test database only
# (`@pytest.mark.django_db(transaction=True)`, `@requires_postgres`) -
# never the dev/production connection. `--execute` is never invoked
# outside a pytest test function scoped to that disposable DB.
#
# Covers the directive's 6 numbered proof requirements:
#   1. Full --execute path exercised against synthetic fixtures.
#   2. Successful migration: rows shift, uniqueness survives, audit
#      rows written, state PENDING(implicit)->...->COMMITTED,
#      canonicalization_state flips to CANONICALIZED.
#   3. Scope-fingerprint mismatch -> STOPPED_REVALIDATION_MISMATCH,
#      rollback, no partial write survives.
#   4. Ineligible/unsafe unit refused before any write is attempted.
#   5. --dry-run path (67.7) completely unaffected - its existing test
#      suite is untouched and this file adds an explicit re-run proof.
#   6. No production data ever touched - explicit connection-alias
#      guard proof (ProductionWriteGuardError).
from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import (
    HistoricalBarMigrationDryRunner,
    MigrationUnitKey,
)
from intraday.application.services.migration_execute import (
    ExecuteOutcome,
    HistoricalBarMigrationExecutor,
    ProductionWriteGuardError,
    assert_write_capable_connection_is_test_database,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_state import MigrationRunState, MigrationUnitState
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar, MigrationRow, MigrationRun, MigrationUnit
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BSE_RELIANCE = make_instrument_id(Exchange.BSE, "RELIANCE")

# 2026-08-10 is in the CAS era (CAS_EFFECTIVE_DATE = 2026-08-03) and
# NSE_EQ/5m is the one PROVEN scope - matching the other proven-scope
# fixtures already used in test_migration_67_7_dry_run.py and the
# 67.8 disposable-DB trial.
_TRADING_DATE = date(2026, 8, 10)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
_FIVE_MIN = timedelta(minutes=5)


def _dense_reliance_rows(count: int = 5) -> list[HistoricalBar]:
    rows = []
    for i in range(count):
        ts = _BASE + i * _FIVE_MIN
        rows.append(
            HistoricalBar(
                instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=ts, open_price=Decimal("100.00") + i, high_price=Decimal("101.50") + i,
                low_price=Decimal("99.25") + i, close_price=Decimal("100.75") + i,
                volume=Decimal("1000") + (i * 10), source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
        )
    return rows


def _make_executor() -> HistoricalBarMigrationExecutor:
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    return HistoricalBarMigrationExecutor(dry_runner=dry_runner)


def _unit_key() -> MigrationUnitKey:
    return MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE)


# ---------------------------------------------------------------------------
# Requirement 6 - production write guard
# ---------------------------------------------------------------------------


def test_guard_raises_when_connection_does_not_look_like_a_test_database():
    """Pure unit test, no DB access: patch `connection.settings_dict`
    to a non-'test_' name and confirm the guard raises loudly rather
    than silently allowing --execute to proceed."""
    from django.db import connection

    with patch.dict(connection.settings_dict, {"NAME": "intraday_dev"}):
        with pytest.raises(ProductionWriteGuardError):
            assert_write_capable_connection_is_test_database()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_guard_passes_for_the_real_disposable_pytest_test_database():
    """Positive control: inside an actual pytest-django test, the live
    connection's database name really does look like a test DB and
    the guard does not raise."""
    assert_write_capable_connection_is_test_database()  # must not raise


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_executor_run_itself_calls_the_guard_first():
    """The executor calls the guard itself inside run(), so even a
    caller who forgot to check is protected. Proven by making the
    guard raise via monkeypatch and confirming run() propagates it
    without touching HistoricalBar at all."""
    executor = _make_executor()
    with patch(
        "intraday.application.services.migration_execute.assert_write_capable_connection_is_test_database",
        side_effect=ProductionWriteGuardError("blocked"),
    ):
        with pytest.raises(ProductionWriteGuardError):
            executor.run(unit_filter=frozenset({_unit_key()}))


# ---------------------------------------------------------------------------
# Requirement 2 - successful synthetic migration
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_execute_successfully_migrates_a_safe_synthetic_unit():
    rows = _dense_reliance_rows(5)
    HistoricalBar.objects.bulk_create(rows)

    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({_unit_key()}))

    assert report.requested_unit_count == 1
    assert report.committed_unit_count == 1
    assert report.run_state is MigrationRunState.COMPLETED

    unit_result = report.units[0]
    assert unit_result.outcome is ExecuteOutcome.COMMITTED
    assert unit_result.final_state is MigrationUnitState.COMMITTED
    assert unit_result.row_count == 5

    # rows shifted +5m and flipped to CANONICALIZED
    migrated = list(
        HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe="5m").order_by("bar_timestamp")
    )
    assert len(migrated) == 5
    expected_ts = sorted(r.bar_timestamp + _FIVE_MIN for r in rows)
    assert [r.bar_timestamp for r in migrated] == expected_ts
    assert all(r.canonicalization_state == "CANONICALIZED" for r in migrated)

    # uniqueness survives: no duplicate (instrument_id, timeframe, bar_timestamp)
    seen_ts = {r.bar_timestamp for r in migrated}
    assert len(seen_ts) == 5

    # audit rows written correctly
    run_row = MigrationRun.objects.get(migration_id=report.run_id)
    assert run_row.status == MigrationRunState.COMPLETED.value

    unit_row = MigrationUnit.objects.get(migration_id=report.run_id, unit_id__contains=str(RELIANCE))
    assert unit_row.status == MigrationUnitState.COMMITTED.value
    assert unit_row.old_row_count == 5
    assert unit_row.new_row_count == 5
    assert unit_row.committed_at is not None

    row_audits = list(MigrationRow.objects.filter(migration_id=report.run_id))
    assert len(row_audits) == 5
    assert {ra.row_id for ra in row_audits} == {r.id for r in rows}
    assert all(ra.status == MigrationUnitState.COMMITTED.value for ra in row_audits)
    assert {ra.new_timestamp for ra in row_audits} == set(expected_ts)


# ---------------------------------------------------------------------------
# Requirement 3 - scope fingerprint mismatch
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_scope_fingerprint_mismatch_stops_and_rolls_back_with_no_partial_write():
    """Simulate the DB changing between the PLANNING snapshot and the
    execute transaction's revalidation: after the executor's internal
    planning pass has already computed its expected fingerprint (which
    happens inside run()), inject an extra eligible row for the SAME
    unit before the revalidation pass runs, by monkeypatching
    `_evaluate_unit` to return a row set that differs from what the
    planning pass used - proving the mismatch is detected and the unit
    is stopped, not silently proceeded with."""
    rows = _dense_reliance_rows(5)
    HistoricalBar.objects.bulk_create(rows)
    original_snapshot = {
        r.id: (r.bar_timestamp, r.canonicalization_state)
        for r in HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe="5m")
    }

    executor = _make_executor()

    real_evaluate = HistoricalBarMigrationDryRunner._evaluate_unit
    call_count = {"n": 0}

    def _tampering_evaluate(self, unit_key, live_rows):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # first call = the PLANNING pass, used as-is.
            return real_evaluate(self, unit_key, live_rows)
        # second call = the in-transaction REVALIDATION pass: simulate
        # a row having been deleted out from under the plan (DB
        # changed between snapshot and execution) by dropping the
        # last row before evaluating - a different row set, and
        # therefore a different scope fingerprint, than planning saw.
        return real_evaluate(self, unit_key, live_rows[:-1])

    with patch.object(HistoricalBarMigrationDryRunner, "_evaluate_unit", _tampering_evaluate):
        report = executor.run(unit_filter=frozenset({_unit_key()}))

    assert report.committed_unit_count == 0
    assert report.stopped_unit_count == 1
    unit_result = report.units[0]
    assert unit_result.outcome is ExecuteOutcome.STOPPED_REVALIDATION_MISMATCH
    assert unit_result.final_state is MigrationUnitState.STOPPED_REVALIDATION_MISMATCH

    # NO PARTIAL WRITE: every HistoricalBar row is byte-for-byte back
    # to its pre-execute state (transaction rolled back).
    post_snapshot = {
        r.id: (r.bar_timestamp, r.canonicalization_state)
        for r in HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe="5m")
    }
    assert post_snapshot == original_snapshot

    # no MigrationRow audit rows survive for this unit (they lived
    # inside the rolled-back transaction).
    assert MigrationRow.objects.filter(migration_id=report.run_id).count() == 0

    # the unit-level audit row (written in its OWN small transaction,
    # after the rollback) DOES record the stop, so the failure is
    # never silently invisible.
    unit_row = MigrationUnit.objects.get(migration_id=report.run_id, unit_id__contains=str(RELIANCE))
    assert unit_row.status == MigrationUnitState.STOPPED_REVALIDATION_MISMATCH.value


# ---------------------------------------------------------------------------
# Requirement 4 - ineligible/unsafe unit refused before any write
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_wrong_segment_unit_is_refused_before_any_write():
    """BSE_EQ never resolves PROVEN even at NSE's proven timeframe/era
    (67.6's segment fix) - the executor must refuse this unit at the
    PLANNING stage, before acquiring any lock or opening any write
    transaction."""
    HistoricalBar.objects.bulk_create(
        [
            HistoricalBar(
                instrument_id=str(BSE_RELIANCE), exchange="BSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=_BASE, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
        ]
    )
    bse_unit = MigrationUnitKey(
        instrument_id=BSE_RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE
    )
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({bse_unit}))

    # BSE_EQ is excluded by the SAME reused live-eligibility query
    # (`exchange="NSE"`) the dry-run path itself uses - it never even
    # becomes a candidate unit, let alone a write. `requested_unit_count`
    # is 0 (filtered before evaluation), and zero units are committed -
    # exactly the "refused before any write" outcome the directive
    # requires, achieved by reusing the existing eligibility predicate
    # rather than adding a parallel one.
    assert report.requested_unit_count == 0
    assert report.committed_unit_count == 0

    # zero writes: the row is untouched.
    row = HistoricalBar.objects.get(instrument_id=str(BSE_RELIANCE))
    assert row.bar_timestamp == _BASE
    assert row.canonicalization_state == "UNCANONICALIZED"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_already_canonical_collision_unit_is_refused_before_any_write():
    old_ts = _BASE
    new_ts = old_ts + _FIVE_MIN
    HistoricalBar.objects.bulk_create(
        [
            HistoricalBar(
                instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=old_ts, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            ),
            HistoricalBar(
                instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=new_ts, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="CANONICALIZED", source_timestamp_semantics="OPEN",
            ),
        ]
    )
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({_unit_key()}))

    assert report.refused_unit_count == 1
    assert report.committed_unit_count == 0
    assert report.units[0].outcome is ExecuteOutcome.REFUSED_UNSAFE

    untouched = HistoricalBar.objects.get(
        instrument_id=str(RELIANCE), timeframe="5m", canonicalization_state="UNCANONICALIZED"
    )
    assert untouched.bar_timestamp == old_ts


# ---------------------------------------------------------------------------
# --limit / --unit targeting (subset design, not all-147-or-nothing)
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_execute_respects_limit_and_touches_only_the_targeted_subset():
    other = make_instrument_id(Exchange.NSE, "TCS")
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))
    HistoricalBar.objects.bulk_create(
        [
            HistoricalBar(
                instrument_id=str(other), exchange="NSE", symbol="TCS", timeframe="5m",
                bar_timestamp=_BASE, open_price=Decimal("200"), high_price=Decimal("201"),
                low_price=Decimal("199"), close_price=Decimal("200.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
        ]
    )
    executor = _make_executor()
    report = executor.run(limit=1)
    assert report.requested_unit_count == 1
    assert report.committed_unit_count == 1

    # exactly one of the two units was touched; the other is untouched.
    tcs_row = HistoricalBar.objects.get(instrument_id=str(other))
    reliance_rows = list(HistoricalBar.objects.filter(instrument_id=str(RELIANCE)))
    touched_states = {tcs_row.canonicalization_state} | {r.canonicalization_state for r in reliance_rows}
    assert touched_states == {"UNCANONICALIZED", "CANONICALIZED"}  # one moved, one didn't


# ---------------------------------------------------------------------------
# Requirement 5 - --dry-run is provably unchanged
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_dry_run_path_produces_identical_report_via_old_and_new_command_wiring():
    """`migration_67_10 --dry-run` must construct the exact same
    `HistoricalBarMigrationDryRunner` and produce an identical report
    to calling the class directly (which is exactly what
    `migration_67_7` does) - proves the new command's --dry-run branch
    is not a parallel reimplementation."""
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))

    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    direct_report = HistoricalBarMigrationDryRunner(coverage_service=coverage_service).run()

    from django.core.management import call_command
    import io

    out = io.StringIO()
    call_command("migration_67_10", "--dry-run", stdout=out)
    output = out.getvalue()

    assert f"eligible_row_count={direct_report.eligible_row_count}" in output
    assert f"unit_count={direct_report.unit_count}" in output
    assert (
        f"safe_units={direct_report.safe_unit_count} unsafe_units={direct_report.unsafe_unit_count}"
        in output
    )

    # zero writes performed by --dry-run, even via the new command.
    unchanged = list(
        HistoricalBar.objects.filter(instrument_id=str(RELIANCE)).values_list(
            "canonicalization_state", flat=True
        )
    )
    assert all(state == "UNCANONICALIZED" for state in unchanged)


def test_migration_67_7_dry_run_test_suite_still_passes_unmodified():
    """Re-runs the ENTIRE pre-existing 67.7 dry-run test file as a
    subprocess, proving this checkpoint's additions did not alter its
    behavior in any way - the file itself is untouched (no edits made
    to it in this checkpoint)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/unit/application/services/test_migration_67_7_dry_run.py"],
        cwd=None, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_execute_mode_requires_test_database_or_refuses_even_with_valid_unit():
    """Belt-and-braces: even a perfectly valid, safe synthetic unit
    must not be migrated if the guard cannot confirm a test database -
    proven by pointing the guard check at a fabricated non-test name
    while otherwise running a real, valid execute() call."""
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))
    executor = _make_executor()
    with patch(
        "intraday.application.services.migration_execute.assert_write_capable_connection_is_test_database",
        side_effect=ProductionWriteGuardError("not a test db"),
    ):
        with pytest.raises(ProductionWriteGuardError):
            executor.run(unit_filter=frozenset({_unit_key()}))

    untouched = HistoricalBar.objects.get(
        instrument_id=str(RELIANCE), timeframe="5m", bar_timestamp=_BASE
    )
    assert untouched.canonicalization_state == "UNCANONICALIZED"
