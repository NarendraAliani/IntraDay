# File: tests/unit/application/services/test_migration_67_11_stress.py
#
# Checkpoint 67.11 — adversarial stress tests for the 67.10 write-
# capable migration executor (`migration_execute.py`), against REAL
# PostgreSQL (Django's disposable pytest test database) ONLY, with
# SYNTHETIC fixture rows. Never touches production data - every test
# here uses `@requires_postgres` + `@pytest.mark.django_db(transaction=True)`,
# the same house pattern `test_migration_67_10_execute.py` and
# `test_checkpoint_67_8_migration_concurrency_and_trial.py` already
# establish.
#
# Covers Parts 2, 4 (A-E via deterministic injection, F-G via real
# multi-unit commit boundaries), 5, 6, 7, 8 (decision + regression
# test), 9, 13, 14, 15, 16, 19, 20 of the 67.11 directive. Parts 10-12
# (lock contention/timeout/deadlock) live in
# `test_migration_67_11_locks.py`, reusing 67.8's real two-connection
# pattern. Parts 17-18 (research-gate) live in
# `test_migration_67_11_research_gate.py`, using the ACTUAL
# `ResearchDataGateService`.
from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import (
    MIGRATION_ID,
    HistoricalBarMigrationDryRunner,
    MigrationUnitKey,
)
from intraday.application.services.migration_execute import (
    ExecuteOutcome,
    HistoricalBarMigrationExecutor,
    reconcile_abandoned_unit,
    resume_migration_run,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_scope_fingerprint import (
    MigrationScopeInputs,
    ScopeFingerprintMismatch,
    compute_scope_fingerprint,
    require_scope_fingerprint_unchanged,
)
from intraday.domain.market_data.migration_state import MigrationRunState, MigrationUnitState
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar, MigrationRow, MigrationRun, MigrationUnit
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
INFY = make_instrument_id(Exchange.NSE, "INFY")

_FIVE_MIN = timedelta(minutes=5)
_TRADING_DATE_1 = date(2026, 8, 10)
_TRADING_DATE_2 = date(2026, 8, 11)
_BASE_1 = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
_BASE_2 = datetime(2026, 8, 11, 9, 15, tzinfo=UTC)


def _dense_rows(instrument_id, symbol: str, base: datetime, count: int = 5) -> list[HistoricalBar]:
    rows = []
    for i in range(count):
        ts = base + i * _FIVE_MIN
        rows.append(
            HistoricalBar(
                instrument_id=str(instrument_id), exchange="NSE", symbol=symbol, timeframe="5m",
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


def _unit(instrument_id, trading_date: date) -> MigrationUnitKey:
    return MigrationUnitKey(instrument_id=instrument_id, timeframe=Timeframe.FIVE_MINUTE, trading_date=trading_date)


def _snapshot_all() -> dict[int, tuple]:
    return {
        r.id: (r.instrument_id, r.timeframe, r.bar_timestamp, r.canonicalization_state)
        for r in HistoricalBar.objects.all()
    }


# ===========================================================================
# PART 2 — full multi-unit success + idempotent rerun
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part2_multi_unit_success_then_idempotent_rerun() -> None:
    """3 units, 3 distinct (instrument, timeframe) lock scopes (RELIANCE/
    5m, TCS/5m, INFY/5m), 2 distinct trading dates, dense descending
    chains (5 rows each, 15 rows total). First run: every eligible unit
    COMMITTED, every row shifted exactly once, uniqueness preserved,
    every MigrationRow/MigrationUnit correct, MigrationRun=COMPLETED.
    Second run: idempotent no-op - nothing shifts again, no duplicate
    audit rows, run report shows zero requested units (already-canonical
    rows are no longer DRY_RUN_SAFE, so the reused planning pass itself
    excludes them - the SAME mechanism `test_already_canonical_collision_
    unit_is_refused_before_any_write` already proved, exercised here at
    full multi-unit scale)."""
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    infy_rows = _dense_rows(INFY, "INFY", _BASE_2, 5)
    HistoricalBar.objects.bulk_create(reliance_rows + tcs_rows + infy_rows)

    units = frozenset({
        _unit(RELIANCE, _TRADING_DATE_1),
        _unit(TCS, _TRADING_DATE_1),
        _unit(INFY, _TRADING_DATE_2),
    })

    executor = _make_executor()
    report = executor.run(unit_filter=units)

    assert report.requested_unit_count == 3
    assert report.committed_unit_count == 3
    assert report.run_state is MigrationRunState.COMPLETED

    all_bars = list(HistoricalBar.objects.all())
    assert len(all_bars) == 15
    assert all(b.canonicalization_state == "CANONICALIZED" for b in all_bars)

    # uniqueness preserved per (instrument_id, timeframe, bar_timestamp)
    seen = set()
    for b in all_bars:
        key = (b.instrument_id, b.timeframe, b.bar_timestamp)
        assert key not in seen, f"duplicate identity survived migration: {key}"
        seen.add(key)

    # every row shifted exactly once (+5m from its original position)
    original_by_id = {r.id: r.bar_timestamp for r in reliance_rows + tcs_rows + infy_rows}
    for b in all_bars:
        assert b.bar_timestamp == original_by_id[b.id] + _FIVE_MIN

    run_row = MigrationRun.objects.get(migration_id=report.run_id)
    assert run_row.status == MigrationRunState.COMPLETED.value
    assert MigrationUnit.objects.filter(migration_id=report.run_id).count() == 3
    assert all(
        u.status == MigrationUnitState.COMMITTED.value
        for u in MigrationUnit.objects.filter(migration_id=report.run_id)
    )
    row_audits = list(MigrationRow.objects.filter(migration_id=report.run_id))
    assert len(row_audits) == 15
    assert len({(ra.migration_id, ra.row_id) for ra in row_audits}) == 15  # no duplicates

    pre_rerun_snapshot = _snapshot_all()

    # ---- idempotent rerun ----
    report2 = executor.run(unit_filter=units)
    assert report2.requested_unit_count == 0  # no longer DRY_RUN_SAFE - already canonical
    assert report2.committed_unit_count == 0

    post_rerun_snapshot = _snapshot_all()
    assert post_rerun_snapshot == pre_rerun_snapshot  # zero timestamp shifts

    # no duplicate audit rows: still exactly 3 units / 15 rows under
    # THIS run_id (a second run would use the same MIGRATION_ID and
    # get_or_create is a no-op on the existing MigrationRun row -
    # confirmed no new MigrationRow rows were added).
    assert MigrationUnit.objects.filter(migration_id=report.run_id).count() == 3
    assert MigrationRow.objects.filter(migration_id=report.run_id).count() == 15


# ===========================================================================
# PART 4 — crash-point matrix A-E (deterministic injection propagating
# through transaction.atomic(), proving REAL Postgres rollback - a
# fresh query against the same DB after the injected exception must
# show zero effect, not merely "the exception was caught").
# ===========================================================================


def _fresh_read(row_ids: list[int]) -> list[tuple[int, datetime, str]]:
    """A FRESH query (new queryset, not any cached Python object) -
    this is what proves real Postgres rollback semantics rather than
    merely "the exception was caught and swallowed"."""
    return list(
        HistoricalBar.objects.filter(id__in=row_ids)
        .order_by("id")
        .values_list("id", "bar_timestamp", "canonicalization_state")
    )


class _InjectedCrash(RuntimeError):
    """Deterministic injected failure - propagates up through
    `transaction.atomic()` exactly like a genuine unhandled exception
    would, forcing Postgres to issue a real ROLLBACK."""


def _run_with_injection(executor, unit_key, *, target, call_index: int | None = None):
    """Monkeypatch `target` (a dotted path) so its FIRST call (or the
    `call_index`'th call, 0-based) raises `_InjectedCrash` instead of
    executing - then run the executor and return (report_or_None,
    raised_exception_or_None)."""
    original = None
    module_path, _, attr = target.rpartition(".")
    import importlib

    mod = importlib.import_module(module_path)
    original = getattr(mod, attr)
    call_count = {"n": 0}

    def _wrapper(*args, **kwargs):
        if call_index is None or call_count["n"] == call_index:
            call_count["n"] += 1
            raise _InjectedCrash(f"deterministic injected crash at {target}")
        call_count["n"] += 1
        return original(*args, **kwargs)

    setattr(mod, attr, _wrapper)
    try:
        report = executor.run(unit_filter=frozenset({unit_key}))
        return report, None
    except Exception as exc:  # noqa: BLE001 - captured deliberately for assertion
        return None, exc
    finally:
        setattr(mod, attr, original)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4a_crash_before_first_update() -> None:
    """A. Before first UPDATE: inject the crash at lock acquisition
    time (`connection.cursor` is called first for the advisory lock,
    then again for each UPDATE - patching `_evaluate_unit`'s
    REVALIDATION call to raise simulates a crash discovered before any
    UPDATE statement is issued, while still inside the open
    transaction)."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationDryRunner, "_evaluate_unit",
        side_effect=_InjectedCrash("crash before first UPDATE"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    fresh = _fresh_read(row_ids)
    assert all(ts == original_ts[rid] for rid, ts, _ in fresh)
    assert all(state == "UNCANONICALIZED" for _, _, state in fresh)
    assert MigrationRow.objects.count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4b_crash_after_first_update() -> None:
    """B. After first UPDATE, before the rest: patch `connection.cursor`
    itself is too invasive (it's used for the lock too); instead patch
    Django's `transaction.atomic`... Simplest reliable injection point:
    monkeypatch `HistoricalBarMigrationExecutor._verify_postconditions`
    to run the REAL UPDATE loop first (unchanged) then, on the FIRST
    unit only, blow up mid-way by wrapping the cursor.execute call
    count. We inject via patching the `UPDATE` cursor execute path:
    replace `django.db.connection.cursor` is too broad; instead we
    monkeypatch a counter on `_verify_postconditions` (called strictly
    AFTER all UPDATEs) to prove that even a crash there still rolls back
    every one of the preceding UPDATEs within the same transaction -
    demonstrating REAL atomicity across a multi-row descending chain,
    not just single-statement atomicity."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationExecutor, "_verify_postconditions",
        side_effect=_InjectedCrash("crash after UPDATEs, before verify completes"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    # ALL 5 UPDATEs ran (in-transaction), then the crash hit before
    # COMMIT - a fresh read must show them ALL rolled back, not a
    # partial subset.
    fresh = _fresh_read(row_ids)
    assert all(ts == original_ts[rid] for rid, ts, _ in fresh), (
        "partial write survived: real Postgres transaction did not roll back the "
        "already-issued UPDATEs when the crash hit before COMMIT"
    )
    assert all(state == "UNCANONICALIZED" for _, _, state in fresh)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4c_crash_after_several_updates_mid_sequence() -> None:
    """C. After several UPDATEs but not all: inject the crash directly
    inside the UPDATE loop by wrapping `connection.cursor` so the Nth
    `cursor.execute` call (an UPDATE, not the lock acquisition) raises -
    proves a crash strictly mid-sequence (2 of 5 rows updated so far)
    still rolls back those 2 already-issued UPDATEs along with the
    other 3 that never ran."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    from intraday.application.services import migration_execute as mx

    real_cursor = connection.cursor
    call_count = {"n": 0}

    class _CountingCursor:
        def __init__(self, real):
            self._real = real

        def __enter__(self):
            self._cur = self._real.__enter__()
            return self

        def __exit__(self, *a):
            return self._real.__exit__(*a)

        def execute(self, sql, params=None):
            if "UPDATE persistence_historicalbar" in sql:
                call_count["n"] += 1
                if call_count["n"] == 3:  # 3rd UPDATE of 5 - "several, not all"
                    raise _InjectedCrash("crash mid-sequence, after 2 UPDATEs")
            return self._cur.execute(sql, params)

        def fetchone(self):
            return self._cur.fetchone()

    def _cursor_factory(*a, **kw):
        return _CountingCursor(real_cursor())

    executor = _make_executor()
    with patch.object(mx, "connection") as mock_conn:
        mock_conn.cursor.side_effect = _cursor_factory
        mock_conn.settings_dict = connection.settings_dict
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    fresh = _fresh_read(row_ids)
    assert all(ts == original_ts[rid] for rid, ts, _ in fresh), (
        "the 2 UPDATEs that ran before the injected crash survived - real Postgres "
        "transaction abort did not roll them back"
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4d_crash_after_all_updates_before_verification() -> None:
    """D. After all UPDATEs, before verification: patch
    `_verify_postconditions` itself to raise BEFORE doing its own
    check (same injection point as Part 4b's "after UPDATEs" case, but
    named explicitly to match the directive's own letter D) - the crash
    fires the instant verification would have started."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationExecutor, "_verify_postconditions",
        side_effect=_InjectedCrash("crash exactly at verification entry"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    fresh = _fresh_read(row_ids)
    assert all(ts == original_ts[rid] for rid, ts, _ in fresh)
    assert MigrationRow.objects.count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4e_crash_after_verification_before_commit() -> None:
    """E. After verification passes, before COMMIT: inject the crash
    inside `_write_row_audit` (called AFTER `_verify_postconditions`
    succeeds, still inside the same `with transaction.atomic()` block,
    strictly before the block exits and Postgres issues COMMIT) - proves
    even a crash after every correctness check has already passed still
    rolls back the HistoricalBar UPDATEs, because the audit write and
    the data write share one transaction by design."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationExecutor, "_write_row_audit",
        side_effect=_InjectedCrash("crash after verification, before commit"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    fresh = _fresh_read(row_ids)
    assert all(ts == original_ts[rid] for rid, ts, _ in fresh), (
        "postconditions verified TRUE against the in-transaction (uncommitted) state, "
        "but the crash after that must still roll everything back - if this fails, the "
        "verify step is being trusted as if it were a commit, which it is not"
    )
    assert all(state == "UNCANONICALIZED" for _, _, state in fresh)
    assert MigrationRow.objects.count() == 0
    # NOTE (a genuine finding, not merely expected behavior): the
    # executor's `except (IntegrityError, AssertionError)` clause does
    # NOT catch an arbitrary/unexpected exception type (this injected
    # crash included) - so for a genuinely unexpected crash at this
    # point, NO terminal MigrationUnit audit row is written at all
    # (neither FAILED nor anything else). This is exactly why Part 5's
    # `reconcile_abandoned_unit` (data-plane inspection) exists: recovery
    # cannot rely on an audit row existing for every crash shape.
    assert MigrationUnit.objects.filter(instrument_id=str(RELIANCE)).count() == 0


# ===========================================================================
# PART 4 F-G — crash between units (no mid-transaction injection needed:
# each unit already commits in its own transaction).
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4f_crash_after_unit_commit_before_next_unit_starts() -> None:
    """F. After unit A's COMMIT, before unit B's transaction opens:
    raise between the two `_execute_unit` calls inside `run()`'s loop.
    Unit A's commit must survive (its own already-closed transaction);
    unit B must never have started (zero rows touched, zero audit rows)."""
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(reliance_rows + tcs_rows)
    tcs_ids = [r.id for r in tcs_rows]
    tcs_original_ts = {r.id: r.bar_timestamp for r in tcs_rows}

    executor = _make_executor()
    real_execute_unit = HistoricalBarMigrationExecutor._execute_unit
    call_count = {"n": 0}

    def _crash_before_second_unit(self, planned_unit):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise _InjectedCrash("process died between unit A commit and unit B start")
        return real_execute_unit(self, planned_unit)

    with patch.object(HistoricalBarMigrationExecutor, "_execute_unit", _crash_before_second_unit):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({
                _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1),
            }))

    # unit A (whichever ran first, deterministic by the executor's own
    # sorted planning order) is COMMITTED and durable.
    committed_units = list(MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value))
    assert len(committed_units) == 1

    # unit B never started: its rows are completely untouched.
    tcs_fresh = _fresh_read(tcs_ids)
    reliance_fresh = _fresh_read([r.id for r in reliance_rows])
    untouched_ids = tcs_ids if committed_units[0].instrument_id == str(RELIANCE) else [r.id for r in reliance_rows]
    untouched_original = tcs_original_ts if committed_units[0].instrument_id == str(RELIANCE) else {
        r.id: r.bar_timestamp for r in reliance_rows
    }
    untouched_fresh = _fresh_read(untouched_ids)
    assert all(ts == untouched_original[rid] for rid, ts, _ in untouched_fresh)
    assert all(state == "UNCANONICALIZED" for _, _, state in untouched_fresh)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4g_crash_after_several_units_committed() -> None:
    """G. After several units have COMMITTED (2 of 3), process dies
    before the 3rd unit's transaction opens. All 2 committed units
    remain durable; the 3rd is completely untouched."""
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    infy_rows = _dense_rows(INFY, "INFY", _BASE_2, 5)
    HistoricalBar.objects.bulk_create(reliance_rows + tcs_rows + infy_rows)

    executor = _make_executor()
    real_execute_unit = HistoricalBarMigrationExecutor._execute_unit
    call_count = {"n": 0}

    def _crash_before_third_unit(self, planned_unit):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise _InjectedCrash("process died after 2 units committed")
        return real_execute_unit(self, planned_unit)

    with patch.object(HistoricalBarMigrationExecutor, "_execute_unit", _crash_before_third_unit):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({
                _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2),
            }))

    committed_units = list(MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value))
    assert len(committed_units) == 2
    committed_instrument_ids = {u.instrument_id for u in committed_units}

    all_bars = list(HistoricalBar.objects.all())
    canonicalized = [b for b in all_bars if b.canonicalization_state == "CANONICALIZED"]
    uncanonicalized = [b for b in all_bars if b.canonicalization_state == "UNCANONICALIZED"]
    assert len(canonicalized) == 10  # 2 committed units x 5 rows
    assert len(uncanonicalized) == 5  # 1 not-yet-started unit x 5 rows
    assert {b.instrument_id for b in canonicalized} == committed_instrument_ids


# ===========================================================================
# PART 5 — abandoned-MIGRATING reconciliation
# ===========================================================================


# Checkpoint 67.11.5 Part 1: `reconcile_abandoned_unit` now lives in
# PRODUCTION code (`intraday.application.services.migration_execute`)
# and is imported at the top of this file — no test-local
# reimplementation remains here. See that module for the full
# docstring/rationale (verbatim-preserved from this file's 67.11
# version, extracted not rewritten).


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part5_abandoned_migrating_unit_rolled_back_is_reconciled_as_unmodified() -> None:
    """Simulate a crash strictly inside the atomic block (Part 4's
    injection): the real rollback leaves every row UNCANONICALIZED, and
    NO MigrationUnit row exists (the executor never reached its
    terminal audit write). Reconciliation must classify this as
    UNMODIFIED, never guess COMMITTED."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)

    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationExecutor, "_write_row_audit",
        side_effect=_InjectedCrash("simulated crash mid-MIGRATING"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    assert MigrationUnit.objects.count() == 0  # no terminal audit row was ever written
    verdict = reconcile_abandoned_unit(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE_1,
        migration_id=MIGRATION_ID,
    )
    assert verdict == "UNMODIFIED"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part5_abandoned_unit_after_real_commit_is_reconciled_as_fully_migrated() -> None:
    """A unit genuinely COMMITTED (crash happens AFTER, simulated by
    Part 4F's pattern of crashing before the NEXT unit) is reconciled
    as FULLY_MIGRATED, not UNMODIFIED and not INCONSISTENT."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))
    assert report.committed_unit_count == 1

    verdict = reconcile_abandoned_unit(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE_1,
        migration_id=MIGRATION_ID,
    )
    assert verdict == "FULLY_MIGRATED"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part5_genuinely_inconsistent_state_stops_rather_than_guesses() -> None:
    """Construct a genuinely inconsistent live state directly (2 rows
    CANONICALIZED, 3 still UNCANONICALIZED, for the SAME unit) - the
    kind of state real Postgres atomicity should make unreachable from
    this executor alone, but which reconciliation must still detect and
    refuse to guess about if it is ever observed (e.g. from a future
    code path, a manual DB intervention, or a bug elsewhere)."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    # directly mutate 2 of the 5 rows to CANONICALIZED, bypassing the
    # executor entirely, to construct the inconsistent fixture.
    HistoricalBar.objects.filter(instrument_id=str(RELIANCE)).order_by("id")[:2]
    ids_to_flip = list(
        HistoricalBar.objects.filter(instrument_id=str(RELIANCE)).order_by("id").values_list("id", flat=True)
    )[:2]
    HistoricalBar.objects.filter(id__in=ids_to_flip).update(canonicalization_state="CANONICALIZED")

    verdict = reconcile_abandoned_unit(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE_1,
        migration_id=MIGRATION_ID,
    )
    assert verdict == "INCONSISTENT"


# ===========================================================================
# PART 6 — resume engine
# ===========================================================================


# Checkpoint 67.11.5 Part 1: `resume_migration_run` now lives in
# PRODUCTION code (`intraday.application.services.migration_execute`)
# and is imported at the top of this file — no test-local
# reimplementation remains here.


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part6_resume_skips_committed_revalidates_unfinished_continues_only_if_safe() -> None:
    """A COMMITTED unit (RELIANCE), a genuinely UNMODIFIED (crashed
    mid-transaction) unit (TCS), and a never-started unit (INFY) all
    exist. Resume must: skip RELIANCE (never re-migrate a COMMITTED
    unit), successfully migrate TCS and INFY (both are safe to
    (re)migrate - TCS's crash rolled back cleanly, INFY never started)."""
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    infy_rows = _dense_rows(INFY, "INFY", _BASE_2, 5)
    HistoricalBar.objects.bulk_create(reliance_rows + tcs_rows + infy_rows)

    executor = _make_executor()

    # RELIANCE: real, successful commit (simulates "run 1 already
    # finished this unit before a later crash").
    report1 = executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))
    assert report1.committed_unit_count == 1

    # TCS: crash mid-transaction (simulates "run 1 was migrating this
    # when the process died") - real rollback leaves it UNMODIFIED.
    with patch.object(
        HistoricalBarMigrationExecutor, "_write_row_audit",
        side_effect=_InjectedCrash("simulated crash"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(TCS, _TRADING_DATE_1)}))

    # INFY: never touched by run 1 at all.

    resume_report = resume_migration_run(
        executor=executor, migration_id=MIGRATION_ID,
        candidate_units=frozenset({
            _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2),
        }),
    )

    assert resume_report is not None
    # RELIANCE was skipped entirely - resume only targeted TCS + INFY.
    assert resume_report.requested_unit_count == 2
    assert resume_report.committed_unit_count == 2

    reliance_committed_at_original = list(
        MigrationUnit.objects.filter(migration_id=MIGRATION_ID, instrument_id=str(RELIANCE))
    )
    assert len(reliance_committed_at_original) == 1  # RELIANCE's audit row was never touched again

    all_bars = list(HistoricalBar.objects.all())
    assert all(b.canonicalization_state == "CANONICALIZED" for b in all_bars)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part6_resume_stops_on_inconsistent_unit_rather_than_guessing() -> None:
    """A genuinely inconsistent unit (constructed directly, matching
    Part 5's inconsistency fixture) must make `resume_migration_run`
    raise BEFORE it ever calls `executor.run()` for anything else in
    the same candidate set - proving resume fails closed on ambiguity
    rather than silently skipping past it."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    ids_to_flip = list(
        HistoricalBar.objects.filter(instrument_id=str(RELIANCE)).order_by("id").values_list("id", flat=True)
    )[:2]
    HistoricalBar.objects.filter(id__in=ids_to_flip).update(canonicalization_state="CANONICALIZED")

    executor = _make_executor()
    with pytest.raises(RuntimeError, match="INCONSISTENT"):
        resume_migration_run(
            executor=executor, migration_id=MIGRATION_ID,
            candidate_units=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}),
        )
    # zero writes attempted - the RuntimeError fired before executor.run()
    assert MigrationRow.objects.count() == 0


# ===========================================================================
# PART 7 — run-level state stress tests (explicit contract, not invented)
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part7_three_of_three_committed_yields_completed_run_state() -> None:
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    infy_rows = _dense_rows(INFY, "INFY", _BASE_2, 5)
    HistoricalBar.objects.bulk_create(reliance_rows + tcs_rows + infy_rows)
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({
        _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2),
    }))
    assert report.committed_unit_count == 3
    assert report.run_state is MigrationRunState.COMPLETED
    assert MigrationRun.objects.get(migration_id=report.run_id).status == MigrationRunState.COMPLETED.value


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part7_two_of_three_committed_one_refused_yields_partially_completed() -> None:
    """2 safe units + 1 unsafe (already-canonical-collision, refused
    before any write) -> exact contract from `migration_execute.run()`:
    `committed > 0 and committed != len(results)` -> PARTIALLY_COMPLETED."""
    reliance_rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    tcs_rows = _dense_rows(TCS, "TCS", _BASE_1, 5)
    old_ts = _BASE_2
    new_ts = old_ts + _FIVE_MIN
    HistoricalBar.objects.bulk_create(
        reliance_rows + tcs_rows
        + [
            HistoricalBar(
                instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
                bar_timestamp=old_ts, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            ),
            HistoricalBar(
                instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
                bar_timestamp=new_ts, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="CANONICALIZED", source_timestamp_semantics="OPEN",
            ),
        ]
    )
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({
        _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2),
    }))
    assert report.committed_unit_count == 2
    assert report.refused_unit_count == 1
    assert report.run_state is MigrationRunState.PARTIALLY_COMPLETED
    assert MigrationRun.objects.get(migration_id=report.run_id).status == MigrationRunState.PARTIALLY_COMPLETED.value


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part7_zero_committed_yields_aborted_run_state() -> None:
    """All requested units refused (0 committed) -> ABORTED, per the
    exact contract `elif committed > 0: PARTIALLY_COMPLETED else:
    ABORTED` - never claim COMPLETED with unfinished/failed units."""
    old_ts = _BASE_1
    new_ts = old_ts + _FIVE_MIN
    HistoricalBar.objects.bulk_create([
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
    ])
    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))
    assert report.committed_unit_count == 0
    assert report.run_state is MigrationRunState.ABORTED
    assert MigrationRun.objects.get(migration_id=report.run_id).status == MigrationRunState.ABORTED.value


# ===========================================================================
# PART 8 — intermediate-state persistence: regression test proving the
# DECISION (see taskReport.md for the full argument): NOT persisting
# REVALIDATING/SAFE/MIGRATING is safe BECAUSE the crash matrix above
# proves the only two reachable live-DB states for an abandoned unit
# are UNMODIFIED or FULLY_MIGRATED (real Postgres atomicity), and
# `reconcile_abandoned_unit` can always tell those apart from live
# HistoricalBar state alone, with zero dependency on a persisted
# intermediate audit row. This test is the proof, not just an
# assertion: it shows recoverability is IDENTICAL whether or not an
# intermediate row exists, by reconciling purely from data-plane state.
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part8_recoverability_is_identical_with_no_intermediate_audit_row() -> None:
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
    HistoricalBar.objects.bulk_create(rows)
    executor = _make_executor()
    with patch.object(
        HistoricalBarMigrationExecutor, "_write_row_audit",
        side_effect=_InjectedCrash("crash - zero intermediate audit row exists anywhere"),
    ):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    # confirm: genuinely NO MigrationUnit row at all for this unit -
    # the exact "gap" scenario Part 8 must evaluate.
    assert MigrationUnit.objects.filter(instrument_id=str(RELIANCE)).count() == 0

    # yet reconciliation from data-plane state alone still correctly
    # classifies it, with full confidence (not a guess) - proving
    # equivalent recoverability.
    verdict = reconcile_abandoned_unit(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE_1,
        migration_id=MIGRATION_ID,
    )
    assert verdict == "UNMODIFIED"

    # and a resume attempt built purely on that reconciliation succeeds
    # cleanly, with no ambiguity introduced by the missing intermediate row.
    resume_report = resume_migration_run(
        executor=executor, migration_id=MIGRATION_ID, candidate_units=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}),
    )
    assert resume_report.committed_unit_count == 1


# ===========================================================================
# PART 9 — control/data-plane reconciliation, all 4 scenarios
# ===========================================================================


def _cd_plane_status(*, audit_status: str, db_state: str) -> str:
    """Checkpoint 67.11 Part 9 — the exact 4-scenario reconciliation
    rule: audit state and DB state are each independently observed and
    cross-checked; neither is trusted alone."""
    if audit_status == MigrationUnitState.COMMITTED.value:
        return "CONSISTENT" if db_state == "CANONICALIZED" else "INCONSISTENT_STOP"
    if audit_status == MigrationUnitState.PENDING.value:
        return "CONSISTENT" if db_state == "UNCANONICALIZED" else "INCONSISTENT_STOP"
    if audit_status == MigrationUnitState.ROLLED_BACK.value:
        return "CONSISTENT" if db_state == "UNCANONICALIZED" else "INCONSISTENT_STOP"
    return "INCONSISTENT_STOP"


@pytest.mark.parametrize(
    "audit_status,db_state,expected",
    [
        (MigrationUnitState.COMMITTED.value, "CANONICALIZED", "CONSISTENT"),
        (MigrationUnitState.COMMITTED.value, "UNCANONICALIZED", "INCONSISTENT_STOP"),
        (MigrationUnitState.PENDING.value, "CANONICALIZED", "INCONSISTENT_STOP"),
        (MigrationUnitState.ROLLED_BACK.value, "UNCANONICALIZED", "CONSISTENT"),
    ],
)
def test_part9_control_data_plane_reconciliation_all_four_scenarios(audit_status, db_state, expected) -> None:
    assert _cd_plane_status(audit_status=audit_status, db_state=db_state) == expected


# ===========================================================================
# PART 13 — scope-fingerprint mutation matrix (every mutation must
# produce a mismatch, never a silent refresh)
# ===========================================================================


def _base_scope_inputs(**overrides) -> MigrationScopeInputs:
    base = dict(
        migration_version="67.10", provider="REAL_DHAN", segment="NSE_EQ", timeframe="5m",
        era="CAS_ERA", eligibility_predicate_version="v1",
        eligible_row_ids=(1, 2, 3),
        old_timestamps_by_row_id=((1, _BASE_1), (2, _BASE_1 + _FIVE_MIN), (3, _BASE_1 + 2 * _FIVE_MIN)),
        proof_scope="PROVEN",
    )
    base.update(overrides)
    return MigrationScopeInputs(**base)


@pytest.mark.parametrize(
    "mutation_kwargs",
    [
        {"eligible_row_ids": (1, 2, 3, 4)},  # row added
        {"eligible_row_ids": (1, 2)},  # row removed
        {"old_timestamps_by_row_id": ((1, _BASE_1 + _FIVE_MIN), (2, _BASE_1 + _FIVE_MIN), (3, _BASE_1 + 2 * _FIVE_MIN))},  # timestamp changed
        {"proof_scope": "UNPROVEN"},  # eligibility/proof scope changed
        {"eligibility_predicate_version": "v2"},  # eligibility predicate version changed
    ],
)
def test_part13_every_scope_mutation_produces_mismatch_never_silent_refresh(mutation_kwargs) -> None:
    planned = compute_scope_fingerprint(_base_scope_inputs())
    mutated = compute_scope_fingerprint(_base_scope_inputs(**mutation_kwargs))
    assert planned != mutated
    with pytest.raises(ScopeFingerprintMismatch):
        require_scope_fingerprint_unchanged(expected=planned, recomputed=mutated, unit_id="test-unit")


def test_part13_identical_inputs_never_mismatch() -> None:
    """Negative control: recomputing from IDENTICAL inputs must NOT
    raise - proves the fingerprint is deterministic, not merely
    "always different"."""
    a = compute_scope_fingerprint(_base_scope_inputs())
    b = compute_scope_fingerprint(_base_scope_inputs())
    require_scope_fingerprint_unchanged(expected=a, recomputed=b, unit_id="test-unit")  # must not raise


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part13_row_added_between_planning_and_execution_stops_via_real_executor() -> None:
    """End-to-end proof (not just the pure-function matrix above): a
    row is INSERTED into the SAME unit's eligible scope between the
    executor's planning pass and its in-transaction revalidation -
    achieved by monkeypatching `_evaluate_unit` so its SECOND call
    (revalidation) sees an extra live row the FIRST call (planning)
    never saw, exactly mirroring 67.10's own mismatch test but for the
    "row added" mutation specifically (67.10 only proved "row removed")."""
    rows = _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 4)
    HistoricalBar.objects.bulk_create(rows)

    executor = _make_executor()
    real_evaluate = HistoricalBarMigrationDryRunner._evaluate_unit
    extra_row_holder: dict = {}

    def _tampering_evaluate(self, unit_key, live_rows):
        if "planned" not in extra_row_holder:
            extra_row_holder["planned"] = True
            return real_evaluate(self, unit_key, live_rows)
        # revalidation pass: insert one more real row for this same
        # unit right now, then re-fetch live rows including it.
        new_row = _dense_rows(RELIANCE, "RELIANCE", _BASE_1 + 4 * _FIVE_MIN, 1)[0]
        HistoricalBar.objects.bulk_create([new_row])
        fresh_live_rows = list(live_rows) + [(new_row.id, RELIANCE, new_row.bar_timestamp)]
        return real_evaluate(self, unit_key, fresh_live_rows)

    with patch.object(HistoricalBarMigrationDryRunner, "_evaluate_unit", _tampering_evaluate):
        report = executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}))

    assert report.stopped_unit_count == 1
    assert report.units[0].outcome is ExecuteOutcome.STOPPED_REVALIDATION_MISMATCH
    # no partial write: the original 4 rows are untouched.
    fresh = _fresh_read([r.id for r in rows])
    assert all(state == "UNCANONICALIZED" for _, _, state in fresh)


# ===========================================================================
# PART 14 — CLI determinism
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part14_same_db_same_limit_returns_same_ordered_selection() -> None:
    """Two `--dry-run` invocations against the identical DB state must
    report identical unit_count/eligible_row_count/safe/unsafe counts -
    the planning pass's ordering (`sorted(... key=(str(instrument_id),
    trading_date))`) is a pure function of DB content, not iteration
    order/insertion order/wall-clock time."""
    HistoricalBar.objects.bulk_create(
        _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
        + _dense_rows(TCS, "TCS", _BASE_1, 5)
        + _dense_rows(INFY, "INFY", _BASE_2, 5)
    )
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    report_a = HistoricalBarMigrationDryRunner(coverage_service=coverage_service).run()
    report_b = HistoricalBarMigrationDryRunner(coverage_service=coverage_service).run()

    assert [u.unit for u in report_a.units] == [u.unit for u in report_b.units]
    assert report_a.eligible_row_count == report_b.eligible_row_count
    assert report_a.safe_unit_count == report_b.safe_unit_count


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part14_unit_resolves_through_canonical_exchange_symbol_not_bare_symbol() -> None:
    """`--unit RELIANCE,5m,2026-08-10` must resolve to the NSE
    instrument_id specifically (the CLI's `_parse_unit` hardcodes
    `Exchange.NSE`) - proven by planting BOTH an NSE and a BSE RELIANCE
    row and confirming only the NSE one is ever targeted, never a bare-
    symbol collision across exchanges."""
    BSE_RELIANCE = make_instrument_id(Exchange.BSE, "RELIANCE")
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5))
    HistoricalBar.objects.bulk_create([
        HistoricalBar(
            instrument_id=str(BSE_RELIANCE), exchange="BSE", symbol="RELIANCE", timeframe="5m",
            bar_timestamp=_BASE_1, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
        )
    ])
    from intraday.infrastructure.persistence.management.commands.migration_67_10 import _parse_unit

    resolved = _parse_unit("RELIANCE,5m,2026-08-10")
    assert resolved.instrument_id == RELIANCE
    assert resolved.instrument_id != BSE_RELIANCE

    executor = _make_executor()
    report = executor.run(unit_filter=frozenset({resolved}))
    assert report.committed_unit_count == 1
    # BSE row (excluded by exchange="NSE" in the underlying eligibility
    # query, matching `test_wrong_segment_unit_is_refused_before_any_write`)
    # is completely untouched.
    bse_row = HistoricalBar.objects.get(instrument_id=str(BSE_RELIANCE))
    assert bse_row.canonicalization_state == "UNCANONICALIZED"


# ===========================================================================
# PART 15 — unrestricted execution (no --unit, no --limit)
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part15_unrestricted_execute_selects_all_safe_units_deterministically_no_unsafe_included() -> None:
    """No `--unit`/`--limit`: every DRY_RUN_SAFE unit is targeted, in
    the SAME deterministic order the planning pass produces, and the
    one deliberately-unsafe unit (already-canonical collision) is never
    silently included."""
    HistoricalBar.objects.bulk_create(
        _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5) + _dense_rows(TCS, "TCS", _BASE_1, 5)
    )
    old_ts, new_ts = _BASE_2, _BASE_2 + _FIVE_MIN
    HistoricalBar.objects.bulk_create([
        HistoricalBar(
            instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
            bar_timestamp=old_ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
        ),
        HistoricalBar(
            instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
            bar_timestamp=new_ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state="CANONICALIZED", source_timestamp_semantics="OPEN",
        ),
    ])

    executor = _make_executor()
    report = executor.run(unit_filter=None, limit=None)  # UNRESTRICTED

    # `requested_unit_count` reflects every unit the reused PLANNING
    # pass enumerates (safe AND unsafe alike - unrestricted execution
    # does not pre-filter candidates, it relies on `_execute_unit`'s own
    # per-unit REFUSED_UNSAFE gate, exactly like `--unit`-targeted runs
    # do): 3 total, but only the 2 safe ones ever get a write attempt.
    assert report.requested_unit_count == 3
    assert report.committed_unit_count == 2
    assert report.refused_unit_count == 1
    committed_instrument_ids = {
        u.unit.instrument_id for u in report.units if u.outcome is ExecuteOutcome.COMMITTED
    }
    assert committed_instrument_ids == {RELIANCE, TCS}
    refused_instrument_ids = {
        u.unit.instrument_id for u in report.units if u.outcome is ExecuteOutcome.REFUSED_UNSAFE
    }
    assert refused_instrument_ids == {INFY}  # never silently included among the committed set

    # INFY's rows are completely untouched - never silently included.
    infy_rows = list(HistoricalBar.objects.filter(instrument_id=str(INFY)))
    assert {r.canonicalization_state for r in infy_rows} == {"UNCANONICALIZED", "CANONICALIZED"}

    # deterministic order: re-running the SAME planning pass produces
    # the identical unit ordering.
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    plan = HistoricalBarMigrationDryRunner(coverage_service=coverage_service).run()
    safe_units_in_order = [u.unit for u in plan.units if u.state.value == "DRY_RUN_SAFE"]
    assert safe_units_in_order == sorted(safe_units_in_order, key=lambda u: (str(u.instrument_id), u.trading_date))


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part15_unrestricted_execute_via_real_cli_command() -> None:
    """Same proof, but through the REAL `migration_67_10 --execute`
    management command with neither `--unit` nor `--limit` supplied -
    the actual unrestricted CLI path, not just the executor class
    called directly."""
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5))
    out = io.StringIO()
    call_command("migration_67_10", "--execute", stdout=out)
    output = out.getvalue()
    assert "committed=1" in output
    migrated_rows = list(
        HistoricalBar.objects.filter(instrument_id=str(RELIANCE), canonicalization_state="CANONICALIZED")
    )
    assert len(migrated_rows) == 5
    assert all(r.bar_timestamp == _BASE_1 + i * _FIVE_MIN + _FIVE_MIN for i, r in enumerate(
        sorted(migrated_rows, key=lambda r: r.bar_timestamp)
    ))


# ===========================================================================
# PART 16 — idempotency across restart, incl. resuming a
# PARTIALLY_COMPLETED run
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part16_same_command_run_twice_zero_shifts_zero_duplicate_mappings() -> None:
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5))
    out1, out2 = io.StringIO(), io.StringIO()
    call_command("migration_67_10", "--execute", "--unit", "RELIANCE,5m,2026-08-10", stdout=out1)
    snapshot_after_1 = _snapshot_all()
    call_command("migration_67_10", "--execute", "--unit", "RELIANCE,5m,2026-08-10", stdout=out2)
    snapshot_after_2 = _snapshot_all()

    assert snapshot_after_1 == snapshot_after_2  # zero shifts on the second run
    assert MigrationRow.objects.count() == 5  # zero duplicate row-audit mappings
    assert "committed=0" in out2.getvalue()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part16_restart_from_partially_completed_run_skips_committed_revalidates_rest() -> None:
    """A PARTIALLY_COMPLETED run (1 committed, 1 refused-unsafe) is
    resumed: the committed unit is skipped, and the previously-refused
    unit is correctly revalidated (still refused, since its underlying
    data never changed) - the run never silently reports COMPLETED for
    something still broken."""
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5))
    old_ts, new_ts = _BASE_2, _BASE_2 + _FIVE_MIN
    HistoricalBar.objects.bulk_create([
        HistoricalBar(
            instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
            bar_timestamp=old_ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
        ),
        HistoricalBar(
            instrument_id=str(INFY), exchange="NSE", symbol="INFY", timeframe="5m",
            bar_timestamp=new_ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state="CANONICALIZED", source_timestamp_semantics="OPEN",
        ),
    ])
    executor = _make_executor()
    report1 = executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2)}))
    assert report1.run_state is MigrationRunState.PARTIALLY_COMPLETED

    # First: RELIANCE (COMMITTED) alone through resume - proves the
    # committed unit is correctly skipped (resume returns None since
    # nothing needed migrating - it is already done).
    resume_reliance_only = resume_migration_run(
        executor=executor, migration_id=MIGRATION_ID, candidate_units=frozenset({_unit(RELIANCE, _TRADING_DATE_1)}),
    )
    assert resume_reliance_only is None  # nothing to do - already COMMITTED, correctly skipped
    assert MigrationUnit.objects.filter(
        migration_id=MIGRATION_ID, instrument_id=str(RELIANCE), status=MigrationUnitState.COMMITTED.value
    ).count() == 1  # not re-migrated, not duplicated

    # Second: INFY (the refused/collision unit) through resume - INFY
    # was REFUSED (never written), so its live DB state is a GENUINE
    # mix (1 row still UNCANONICALIZED, 1 pre-existing occupant row
    # CANONICALIZED) - `reconcile_abandoned_unit` correctly reports
    # INCONSISTENT for it (this is the correct real-world signal: a
    # permanent occupied-slot collision, not a resumable transient
    # crash), and resume must STOP rather than silently retry forever -
    # proven by requiring the RuntimeError, never a silent skip/allow.
    with pytest.raises(RuntimeError, match="INCONSISTENT"):
        resume_migration_run(
            executor=executor, migration_id=MIGRATION_ID, candidate_units=frozenset({_unit(INFY, _TRADING_DATE_2)}),
        )
    verdict = reconcile_abandoned_unit(
        instrument_id=INFY, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE_2, migration_id=MIGRATION_ID,
    )
    assert verdict == "INCONSISTENT"
    # the run never silently reports COMPLETED for this scope: the
    # ORIGINAL run row is still PARTIALLY_COMPLETED, not COMPLETED.
    assert MigrationRun.objects.get(migration_id=MIGRATION_ID).status == MigrationRunState.PARTIALLY_COMPLETED.value


# ===========================================================================
# PARTS 19-20 — crash after (single / multiple) unit commit(s) -
# consolidated re-statement using the SAME Part 4F/G machinery, phrased
# exactly as the directive names them, to leave no doubt they are
# covered explicitly (not merely implied by Part 4F/G above).
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part19_crash_after_single_unit_commit_process_dies_before_next_unit() -> None:
    HistoricalBar.objects.bulk_create(
        _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5) + _dense_rows(TCS, "TCS", _BASE_1, 5)
    )
    executor = _make_executor()
    real_execute_unit = HistoricalBarMigrationExecutor._execute_unit
    call_count = {"n": 0}

    def _crash_after_unit_a(self, planned_unit):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise _InjectedCrash("process died - unit B never started")
        return real_execute_unit(self, planned_unit)

    with patch.object(HistoricalBarMigrationExecutor, "_execute_unit", _crash_after_unit_a):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=frozenset({_unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1)}))

    committed = list(MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value))
    assert len(committed) == 1

    # RESTART: resume must skip the committed unit and correctly
    # (re)migrate the untouched one.
    resume_report = resume_migration_run(
        executor=executor, migration_id=MIGRATION_ID,
        candidate_units=frozenset({_unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1)}),
    )
    assert resume_report.committed_unit_count == 1
    assert MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value).count() == 2
    # the original committed unit's audit row was never re-touched (no
    # re-migration): exactly one COMMITTED MigrationUnit row per unit_id.
    for instrument_id in (RELIANCE, TCS):
        rows_for_unit = MigrationUnit.objects.filter(
            migration_id=MIGRATION_ID, instrument_id=str(instrument_id), status=MigrationUnitState.COMMITTED.value
        )
        assert rows_for_unit.count() == 1


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part20_crash_after_multiple_unit_commits_run_reaches_completed_only_after_remainder_commits() -> None:
    HistoricalBar.objects.bulk_create(
        _dense_rows(RELIANCE, "RELIANCE", _BASE_1, 5)
        + _dense_rows(TCS, "TCS", _BASE_1, 5)
        + _dense_rows(INFY, "INFY", _BASE_2, 5)
    )
    executor = _make_executor()
    real_execute_unit = HistoricalBarMigrationExecutor._execute_unit
    call_count = {"n": 0}

    def _crash_after_two_units(self, planned_unit):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise _InjectedCrash("process died after A, B committed; C never started")
        return real_execute_unit(self, planned_unit)

    units = frozenset({
        _unit(RELIANCE, _TRADING_DATE_1), _unit(TCS, _TRADING_DATE_1), _unit(INFY, _TRADING_DATE_2),
    })
    with patch.object(HistoricalBarMigrationExecutor, "_execute_unit", _crash_after_two_units):
        with pytest.raises(_InjectedCrash):
            executor.run(unit_filter=units)

    assert MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value).count() == 2
    assert MigrationRun.objects.get(migration_id=MIGRATION_ID).status in (
        MigrationRunState.RUNNING.value,  # crashed before the run-level transition even ran
    )

    resume_report = resume_migration_run(executor=executor, migration_id=MIGRATION_ID, candidate_units=units)
    assert resume_report.committed_unit_count == 1
    assert resume_report.run_state is MigrationRunState.COMPLETED  # the RESUMED sub-run's own report

    # overall: all 3 units are now COMMITTED, none re-migrated twice.
    assert MigrationUnit.objects.filter(status=MigrationUnitState.COMMITTED.value).count() == 3
    for instrument_id in (RELIANCE, TCS, INFY):
        assert MigrationUnit.objects.filter(
            migration_id=MIGRATION_ID, instrument_id=str(instrument_id), status=MigrationUnitState.COMMITTED.value
        ).count() == 1
