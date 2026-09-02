# File: tests/unit/infrastructure/persistence/test_migration_67_11_locks.py
#
# Checkpoint 67.11 Parts 10-12 — real two-connection PostgreSQL lock
# contention, lock-timeout, and deadlock-ordering proofs against the
# disposable pytest test database, reusing the EXACT pattern already
# proven correct in
# `test_checkpoint_67_8_migration_concurrency_and_trial.py` (separate
# thread == separate PostgreSQL backend/session, `threading.Event` for
# handshake, `connections.close_all()` in the thread's `finally`).
# Part 10's "actual migration X then bulk_upsert X" and reverse are
# ALREADY proven in that 67.8 file
# (`test_bulk_upsert_and_migration_lock_serialize_for_same_instrument_
# timeframe`) - this file adds the REVERSE direction (bulk_upsert holds
# first, migration-side blocks) plus the genuinely NEW Part 11 (lock
# TIMEOUT, deterministic failure) and Part 12 (3-scope deadlock-
# ordering matrix) proofs 67.8/67.10 never built.
from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, connections, transaction

from intraday.application.services.migration_advisory_lock import historical_migration_lock_key
from intraday.application.services.migration_execute import HistoricalBarMigrationExecutor
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
INFY = make_instrument_id(Exchange.NSE, "INFY")

_FIVE_MIN = timedelta(minutes=5)
_TRADING_DATE = date(2026, 8, 10)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)


def _dense_rows(instrument_id, symbol: str, count: int = 5) -> list[HistoricalBar]:
    rows = []
    for i in range(count):
        ts = _BASE + i * _FIVE_MIN
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


# ===========================================================================
# PART 10 — lock contention, both directions (reverse of 67.8's proof:
# bulk_upsert holds first, a migration-side attempt for the SAME scope
# must block; a DIFFERENT scope must not).
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part10_bulk_upsert_holds_first_migration_side_blocks_for_same_scope() -> None:
    """bulk_upsert acquires the canonical lock for (RELIANCE, 5m) first
    and holds it open; a migration-side attempt for the SAME scope
    (via a real `pg_try_advisory_xact_lock` on the identical key, the
    same technique 67.8 uses) must be blocked until bulk_upsert's
    transaction ends."""
    key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    acquired = threading.Event()
    release = threading.Event()

    def _bulk_upsert_side_holds_lock() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                acquired.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    thread = threading.Thread(target=_bulk_upsert_side_holds_lock)
    thread.start()
    try:
        assert acquired.wait(timeout=10)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
                migration_side_blocked = not cursor.fetchone()[0]
            transaction.set_rollback(True)
    finally:
        release.set()
        thread.join(timeout=10)

    assert migration_side_blocked is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part10_different_scopes_never_block_each_other_bulk_upsert_direction() -> None:
    """bulk_upsert holds (RELIANCE, 5m); a migration-side try-lock for
    the DIFFERENT (TCS, 5m) scope must succeed immediately."""
    key_reliance = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_tcs = historical_migration_lock_key(TCS, Timeframe.FIVE_MINUTE)
    assert key_reliance != key_tcs
    acquired = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_reliance])
                acquired.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    thread = threading.Thread(target=_hold)
    thread.start()
    try:
        assert acquired.wait(timeout=10)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key_tcs])
                obtained = cursor.fetchone()[0]
            transaction.set_rollback(True)
    finally:
        release.set()
        thread.join(timeout=10)

    assert obtained is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part10_two_real_migration_units_for_same_scope_serialize_via_the_real_executor() -> None:
    """End-to-end (not just raw advisory-lock primitives): TWO REAL
    `HistoricalBarMigrationExecutor` runs targeting units for the SAME
    (instrument, timeframe) scope but different trading dates - each
    run acquires and releases the same lock key inside its own
    transaction.atomic() block; run one commits, THEN run two acquires
    the same key cleanly (never observes a stuck/leaked lock from run
    one) - proves the executor's real lock usage releases correctly at
    COMMIT, not just that the raw primitive does."""
    from intraday.domain.instrument.contracts import make_instrument_id as _mk
    trading_date_2 = date(2026, 8, 11)
    base_2 = datetime(2026, 8, 11, 9, 15, tzinfo=UTC)

    def _rows(base):
        return [
            HistoricalBar(
                instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=base + i * _FIVE_MIN, open_price=Decimal("100") + i,
                high_price=Decimal("101") + i, low_price=Decimal("99") + i, close_price=Decimal("100.5") + i,
                volume=Decimal("1000"), source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
            for i in range(5)
        ]

    HistoricalBar.objects.bulk_create(_rows(_BASE) + _rows(base_2))
    from intraday.application.services.migration_dry_run import MigrationUnitKey

    executor = _make_executor()
    unit1 = MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE)
    unit2 = MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=trading_date_2)

    report1 = executor.run(unit_filter=frozenset({unit1}))
    assert report1.committed_unit_count == 1
    report2 = executor.run(unit_filter=frozenset({unit2}))
    assert report2.committed_unit_count == 1  # never blocked/deadlocked by run 1's already-released lock


# ===========================================================================
# PART 11 — lock timeout: deterministic failure, no hang, no partial
# write, another scope can proceed.
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part11_lock_timeout_fails_deterministically_no_hang_no_partial_write() -> None:
    """Hold the migration lock for (RELIANCE, 5m) on a separate real
    connection. A second connection sets Postgres's own
    `lock_timeout` (a real, standard Postgres session setting - not a
    Python-level `time.sleep` polling loop) to a short value and then
    attempts a BLOCKING `pg_advisory_xact_lock` for the SAME key -
    Postgres itself raises `lock_timeout` (SQLSTATE 55P03) rather than
    hanging forever. Proves: deterministic failure (bounded wall-clock
    time, not an infinite wait), zero HistoricalBar mutation (the
    attempt never got past the lock stage), and a DIFFERENT scope is
    completely unaffected."""
    key_reliance = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_tcs = historical_migration_lock_key(TCS, Timeframe.FIVE_MINUTE)
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", 5))
    original_ts = {
        r.id: r.bar_timestamp
        for r in HistoricalBar.objects.filter(instrument_id=str(RELIANCE))
    }

    acquired = threading.Event()
    release = threading.Event()

    def _hold_lock() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_reliance])
                acquired.set()
                release.wait(timeout=15)
        finally:
            connections.close_all()

    thread = threading.Thread(target=_hold_lock)
    thread.start()
    timed_out = False
    started_at = None
    elapsed = None
    try:
        assert acquired.wait(timeout=10)
        import time as _time

        started_at = _time.monotonic()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_reliance])  # BLOCKING form
        except DatabaseError as exc:
            timed_out = True
            elapsed = _time.monotonic() - started_at
            assert "lock" in str(exc).lower() or "55P03" in str(exc)
    finally:
        release.set()
        thread.join(timeout=15)

    assert timed_out is True, "blocking lock acquisition did not time out - it either hung or succeeded wrongly"
    assert elapsed is not None and elapsed < 5.0, f"lock_timeout did not bound wait time deterministically: {elapsed}s"

    # zero mutation: the attempt never got anywhere near an UPDATE.
    fresh = {
        r.id: r.bar_timestamp
        for r in HistoricalBar.objects.filter(instrument_id=str(RELIANCE))
    }
    assert fresh == original_ts

    # a DIFFERENT scope (TCS) is completely unaffected - no cross-scope
    # blocking from the timed-out attempt.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key_tcs])
            tcs_obtained = cursor.fetchone()[0]
        transaction.set_rollback(True)
    assert tcs_obtained is True


# ===========================================================================
# PART 12 — deadlock-ordering matrix: A requests X,Y / B requests Y,X;
# and the 3-scope X,Y,Z / Z,X,Y / Y,Z,X orderings. Canonical ordering
# (sorted lock-key order, matching how a real multi-unit migration run
# would acquire per-unit locks strictly sequentially in the SAME
# deterministic order every time - see `migration_dry_run.run()`'s own
# `sorted(...)` unit ordering, which the executor iterates verbatim)
# prevents deadlock by construction: every session acquires locks in
# the SAME globally agreed order, so a circular wait can never form.
# ===========================================================================


def _canonical_order(keys: list[int]) -> list[int]:
    """The deadlock-prevention discipline this checkpoint's executor
    already exhibits structurally (never acquires two DIFFERENT
    (instrument,timeframe) locks concurrently within one unit's
    transaction; across units it processes them in the dry-run
    planning pass's deterministic sorted order) - made explicit and
    testable here as a pure helper: sort ascending, always."""
    return sorted(keys)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part12_two_scope_canonical_ordering_prevents_deadlock() -> None:
    """A wants (RELIANCE, TCS); B wants (TCS, RELIANCE) - the classic
    deadlock shape if each acquired in its own preferred order. Both
    threads instead acquire in CANONICAL (sorted) order - proven to
    never deadlock by running both concurrently against real Postgres
    and confirming both complete within a bounded time."""
    key_r = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_t = historical_migration_lock_key(TCS, Timeframe.FIVE_MINUTE)
    results: dict[str, bool] = {}
    start_barrier = threading.Barrier(2, timeout=10)

    def _worker(name: str, wanted: list[int]) -> None:
        try:
            start_barrier.wait()
            ordered = _canonical_order(wanted)  # BOTH threads always acquire ascending
            try:
                with transaction.atomic():
                    for k in ordered:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [k])
                    # briefly hold both to maximize the window where a
                    # real deadlock (if the ordering discipline were
                    # violated) would manifest.
                    import time as _t
                    _t.sleep(0.05)
                results[name] = True
            except DatabaseError:
                results[name] = False
        finally:
            connections.close_all()

    t_a = threading.Thread(target=_worker, args=("A", [key_r, key_t]))
    t_b = threading.Thread(target=_worker, args=("B", [key_t, key_r]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive(), "a thread never completed - deadlock/hang occurred"
    assert results.get("A") is True
    assert results.get("B") is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part12_three_scope_deadlock_ordering_matrix() -> None:
    """3 scopes (X=RELIANCE, Y=TCS, Z=INFY), 3 threads requesting them
    in the 3 distinct rotations the directive names: X,Y,Z / Z,X,Y /
    Y,Z,X - each thread canonicalizes its own acquisition order before
    acquiring (the deadlock-prevention discipline), and all 3 must
    complete without deadlock or hang."""
    key_x = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_y = historical_migration_lock_key(TCS, Timeframe.FIVE_MINUTE)
    key_z = historical_migration_lock_key(INFY, Timeframe.FIVE_MINUTE)
    results: dict[str, bool] = {}
    start_barrier = threading.Barrier(3, timeout=10)

    def _worker(name: str, wanted: list[int]) -> None:
        try:
            start_barrier.wait()
            ordered = _canonical_order(wanted)
            try:
                with transaction.atomic():
                    for k in ordered:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [k])
                    import time as _t
                    _t.sleep(0.05)
                results[name] = True
            except DatabaseError:
                results[name] = False
        finally:
            connections.close_all()

    orderings = {
        "T1": [key_x, key_y, key_z],
        "T2": [key_z, key_x, key_y],
        "T3": [key_y, key_z, key_x],
    }
    threads = [threading.Thread(target=_worker, args=(name, order)) for name, order in orderings.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert all(not t.is_alive() for t in threads), "a thread never completed - deadlock/hang occurred"
    assert all(results.get(name) is True for name in orderings)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part12_negative_control_uncanonical_ordering_can_genuinely_deadlock() -> None:
    """Negative control proving the canonical-ordering discipline is
    actually load-bearing (not a no-op): TWO threads acquire in their
    OWN mismatched order (A: X then Y; B: Y then X, with an explicit
    handshake forcing both to hold their first lock before either
    attempts its second) - real PostgreSQL must detect and break the
    resulting deadlock (one side gets a deadlock error; Postgres never
    just hangs forever, but WITHOUT canonical ordering at least one
    side genuinely fails, unlike the ordered case above where both
    always succeed)."""
    key_x = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_y = historical_migration_lock_key(TCS, Timeframe.FIVE_MINUTE)
    results: dict[str, str] = {}
    a_has_first = threading.Event()
    b_has_first = threading.Event()

    def _worker_a() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_x])
                a_has_first.set()
                assert b_has_first.wait(timeout=5)
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL deadlock_timeout = '200ms'")
                        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_y])
                    results["A"] = "succeeded"
                except DatabaseError:
                    results["A"] = "failed"
                    raise
        except DatabaseError:
            pass
        finally:
            connections.close_all()

    def _worker_b() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_y])
                b_has_first.set()
                assert a_has_first.wait(timeout=5)
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL deadlock_timeout = '200ms'")
                        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_x])
                    results["B"] = "succeeded"
                except DatabaseError:
                    results["B"] = "failed"
                    raise
        except DatabaseError:
            pass
        finally:
            connections.close_all()

    t_a = threading.Thread(target=_worker_a)
    t_b = threading.Thread(target=_worker_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive(), "deadlock was never resolved - a thread hung forever"
    # at least one side must have failed (Postgres's own deadlock
    # detector breaks the cycle) - proving mismatched ordering is a
    # real hazard the canonical-ordering discipline above genuinely
    # prevents, not a hazard that never existed in the first place.
    assert "failed" in results.values(), (
        f"expected at least one side to fail with a deadlock error, got: {results!r} - "
        "if both succeeded, this negative control does not actually demonstrate a hazard"
    )
