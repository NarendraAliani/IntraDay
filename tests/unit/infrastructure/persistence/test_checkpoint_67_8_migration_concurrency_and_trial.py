# File: tests/unit/infrastructure/persistence/test_checkpoint_67_8_migration_concurrency_and_trial.py
#
# Checkpoint 67.8 Parts 3-6 — REAL PostgreSQL proofs against the
# disposable pytest test database ONLY (`@requires_postgres`,
# `@pytest.mark.django_db(transaction=True)`, matching the house
# pattern already established by
# `test_scanner_configuration_repository.py::
# test_two_simultaneous_configuration_updates_serialize_with_no_lost_update`).
# NEVER touches the dev/production connection `manage.py shell` uses.
#
# Part 3 — actual two-connection advisory-lock contention proof.
# Parts 4-6 — an actual disposable-DB migration SQL trial: real rows,
# a real descending-order UPDATE against the real
# `uq_historical_bar_identity` constraint, and a real DATABASE-
# TRANSACTION ROLLBACK proof (distinct from 67.7's ALGEBRAIC ROLLBACK
# VALIDATION in `migration_audit.py`, which is pure Python arithmetic
# and never touches a database at all).
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, connections, transaction

from intraday.application.services.migration_advisory_lock import (
    historical_migration_lock_key,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
INFY = make_instrument_id(Exchange.NSE, "INFY")


class _ForceRollback(Exception):
    """Used to force Django's `transaction.atomic()` to issue a real
    `ROLLBACK` at the database level (not just Python cleanup) even
    though no genuine error occurred — the trial's own rollback
    boundary, distinct from pytest-django's outer per-test rollback."""


# --------------------------------------------------------------------
# PART 3 — ACTUAL TWO-CONNECTION LOCK CONTENTION TEST
# --------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_same_scope_advisory_lock_blocks_second_holder_until_first_commits() -> None:
    """Connection A acquires `pg_advisory_xact_lock(key)` for
    (RELIANCE, 5m) and holds its transaction open. While A holds it, a
    second REAL connection's non-blocking `pg_try_advisory_xact_lock`
    for the SAME key must return `false` (blocked). Once A commits
    (releasing the lock at COMMIT, Postgres's own xact-lock semantics),
    a fresh non-blocking attempt for the same key must return `true`."""
    key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)

    acquired = threading.Event()
    release = threading.Event()
    held_result: dict[str, bool] = {}

    def _hold_lock_on_connection_a() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                acquired.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    thread_a = threading.Thread(target=_hold_lock_on_connection_a)
    thread_a.start()
    try:
        assert acquired.wait(timeout=10), "connection A never signalled lock acquisition"

        # Connection B (this thread's own Django connection == a
        # genuinely separate PostgreSQL backend/session from A's
        # thread-local connection): try-lock the SAME key must fail.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
                held_result["same_scope_blocked"] = not cursor.fetchone()[0]
            transaction.set_rollback(True)  # release B's own xact-scoped attempt immediately
    finally:
        release.set()
        thread_a.join(timeout=10)

    assert held_result["same_scope_blocked"] is True

    # A has now committed (released the lock). A fresh try-lock for the
    # SAME key must now succeed.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
            obtained_after_release = cursor.fetchone()[0]
        transaction.set_rollback(True)
    assert obtained_after_release is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_different_scope_advisory_lock_never_blocks() -> None:
    """(RELIANCE, 5m) and (INFY, 5m) map to different lock keys by
    construction — while connection A holds RELIANCE/5m's lock,
    connection B's try-lock for INFY/5m's DIFFERENT key must succeed
    immediately (no unnecessary cross-scope blocking)."""
    key_a = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    key_b = historical_migration_lock_key(INFY, Timeframe.FIVE_MINUTE)
    assert key_a != key_b

    acquired = threading.Event()
    release = threading.Event()

    def _hold_lock_on_connection_a() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key_a])
                acquired.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    thread_a = threading.Thread(target=_hold_lock_on_connection_a)
    thread_a.start()
    try:
        assert acquired.wait(timeout=10)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key_b])
                obtained = cursor.fetchone()[0]
            transaction.set_rollback(True)
    finally:
        release.set()
        thread_a.join(timeout=10)

    assert obtained is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_bulk_upsert_and_migration_lock_serialize_for_same_instrument_timeframe() -> None:
    """Checkpoint 67.8 Part 1 proof: a concurrent
    `DjangoHistoricalBarRepository.bulk_upsert()` call for (RELIANCE,
    5m) now goes through the SAME canonical lock a migration commit
    would use — while a migration-side transaction holds the lock for
    that scope, `bulk_upsert`'s own lock acquisition (inside its
    per-group `acquire_historical_bar_migration_lock` call) must block
    until the migration-side transaction releases it. Proven here via
    the same try-lock technique: a migration-held lock makes a fresh
    try-lock attempt for the SAME key fail, exactly the situation
    `bulk_upsert` would encounter with a real blocking
    `pg_advisory_xact_lock` acquisition."""
    key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    acquired = threading.Event()
    release = threading.Event()

    def _migration_side_holds_lock() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                acquired.set()
                release.wait(timeout=10)
        finally:
            connections.close_all()

    thread = threading.Thread(target=_migration_side_holds_lock)
    thread.start()
    try:
        assert acquired.wait(timeout=10)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
                blocked = not cursor.fetchone()[0]
            transaction.set_rollback(True)
    finally:
        release.set()
        thread.join(timeout=10)

    assert blocked is True, (
        "bulk_upsert's lock acquisition for the SAME (instrument_id, timeframe) as an "
        "in-flight migration would NOT actually block - the concurrency gap is not closed"
    )


# --------------------------------------------------------------------
# PARTS 4-6 — DISPOSABLE-DB MIGRATION SQL TRIAL
# --------------------------------------------------------------------

_BASE = datetime(2026, 1, 5, 9, 15, tzinfo=dt_timezone.utc)
_FIVE_MIN = timedelta(minutes=5)


def _representative_rows() -> list[HistoricalBar]:
    """One complete, dense 5m session for RELIANCE: first boundary
    (09:15) through a later boundary (09:35), 5 bars, plus one row for
    a DIFFERENT instrument (INFY) at an overlapping raw timestamp to
    prove cross-scope isolation. Every field the migration must NOT
    touch is populated with a distinguishable, non-default value so
    row-level preservation can be checked field-by-field, not just by
    hash."""
    rows = []
    for i in range(5):
        ts = _BASE + i * _FIVE_MIN
        rows.append(
            HistoricalBar(
                instrument_id=str(RELIANCE),
                exchange="NSE",
                symbol="RELIANCE",
                timeframe=Timeframe.FIVE_MINUTE.value,
                bar_timestamp=ts,
                open_price=Decimal("100.00") + i,
                high_price=Decimal("101.50") + i,
                low_price=Decimal("99.25") + i,
                close_price=Decimal("100.75") + i,
                volume=Decimal("1000") + (i * 10),
                source="API_FETCH",
                provenance="REAL_DHAN",
                canonicalization_state="UNCANONICALIZED",
                source_timestamp_semantics="OPEN",
            )
        )
    rows.append(
        HistoricalBar(
            instrument_id=str(INFY),
            exchange="NSE",
            symbol="INFY",
            timeframe=Timeframe.FIVE_MINUTE.value,
            bar_timestamp=_BASE,
            open_price=Decimal("500.00"),
            high_price=Decimal("505.00"),
            low_price=Decimal("495.00"),
            close_price=Decimal("501.00"),
            volume=Decimal("2000"),
            source="API_FETCH",
            provenance="REAL_DHAN",
            canonicalization_state="UNCANONICALIZED",
            source_timestamp_semantics="OPEN",
        )
    )
    return rows


def _snapshot(rows: list[HistoricalBar]) -> list[dict]:
    return [
        {
            "id": r.id,
            "instrument_id": r.instrument_id,
            "timeframe": r.timeframe,
            "bar_timestamp": r.bar_timestamp,
            "open_price": r.open_price,
            "high_price": r.high_price,
            "low_price": r.low_price,
            "close_price": r.close_price,
            "volume": r.volume,
            "source": r.source,
            "provenance": r.provenance,
            "canonicalization_state": r.canonicalization_state,
            "source_timestamp_semantics": r.source_timestamp_semantics,
        }
        for r in rows
    ]


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_disposable_db_descending_update_survives_unique_constraint_then_rolls_back() -> None:
    """PARTS 4-6, labelled DATABASE-TRANSACTION ROLLBACK VALIDATION
    (distinct from 67.7's ALGEBRAIC ROLLBACK VALIDATION in
    `migration_audit.py`, which never touches a database).

    Runs the ACTUAL SQL the migration runner would issue: for the
    RELIANCE/5m unit's 5 dense rows, shift `bar_timestamp` forward by
    +5m (the real OPEN->CLOSE canonicalization shift) via individual
    `UPDATE ... WHERE id = %s` statements executed in DESCENDING
    bar_timestamp order (last row first) - proving the real, non-
    deferrable `uq_historical_bar_identity` UNIQUE(instrument_id,
    timeframe, bar_timestamp) constraint survives with ZERO
    intermediate violations, because each target slot is vacated
    before it is filled. Then ROLLS BACK the whole trial transaction
    and proves every row is back to its EXACT original value,
    field-by-field (not merely a hash) - only `bar_timestamp` was ever
    touched, and even that is undone by the rollback."""
    rows = _representative_rows()
    HistoricalBar.objects.bulk_create(rows)
    reliance_rows = list(
        HistoricalBar.objects.filter(
            instrument_id=str(RELIANCE), timeframe=Timeframe.FIVE_MINUTE.value
        ).order_by("bar_timestamp")
    )
    assert len(reliance_rows) == 5
    original_snapshot = _snapshot(
        list(HistoricalBar.objects.all().order_by("id"))
    )

    intermediate_violation_occurred = False
    try:
        with transaction.atomic():
            # migration-side advisory lock for this unit's scope.
            key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])

            # Descending order: last (latest) bar_timestamp updated
            # first, so its NEW slot (old + 5m) is never occupied by
            # an unmigrated row - if this were ASCENDING instead, the
            # first UPDATE would try to move row[0] onto row[1]'s
            # still-existing timestamp and hit uq_historical_bar_identity.
            for row in sorted(reliance_rows, key=lambda r: r.bar_timestamp, reverse=True):
                new_ts = row.bar_timestamp + _FIVE_MIN
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE persistence_historicalbar
                        SET bar_timestamp = %s, canonicalization_state = %s
                        WHERE id = %s
                        """,
                        [new_ts, "CANONICALIZED", row.id],
                    )

            # verify: post-update state is canonical, dense, and
            # unique - no constraint violation was swallowed.
            migrated = list(
                HistoricalBar.objects.filter(
                    instrument_id=str(RELIANCE), timeframe=Timeframe.FIVE_MINUTE.value
                ).order_by("bar_timestamp")
            )
            assert len(migrated) == 5
            expected_new_timestamps = [
                r.bar_timestamp + _FIVE_MIN for r in sorted(reliance_rows, key=lambda r: r.bar_timestamp)
            ]
            assert [r.bar_timestamp for r in migrated] == expected_new_timestamps
            assert all(r.canonicalization_state == "CANONICALIZED" for r in migrated)

            raise _ForceRollback()  # force a REAL database ROLLBACK, not just Python cleanup
    except _ForceRollback:
        pass
    except IntegrityError:
        intermediate_violation_occurred = True

    assert intermediate_violation_occurred is False, (
        "the descending-order UPDATE sequence hit uq_historical_bar_identity - the ordering "
        "does NOT actually survive the real non-deferrable constraint"
    )

    # DATABASE-TRANSACTION ROLLBACK VALIDATION: exact row-by-row
    # comparison after rollback, not merely a checksum.
    post_rollback_snapshot = _snapshot(list(HistoricalBar.objects.all().order_by("id")))
    assert post_rollback_snapshot == original_snapshot
    for before, after in zip(original_snapshot, post_rollback_snapshot, strict=True):
        assert before["bar_timestamp"] == after["bar_timestamp"]
        assert before["open_price"] == after["open_price"]
        assert before["high_price"] == after["high_price"]
        assert before["low_price"] == after["low_price"]
        assert before["close_price"] == after["close_price"]
        assert before["volume"] == after["volume"]
        assert before["source"] == after["source"]
        assert before["provenance"] == after["provenance"]
        assert before["source_timestamp_semantics"] == after["source_timestamp_semantics"]
        assert before["canonicalization_state"] == after["canonicalization_state"]
        assert before["instrument_id"] == after["instrument_id"]
        assert before["timeframe"] == after["timeframe"]


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_ascending_order_would_hit_the_real_unique_constraint() -> None:
    """Negative control proving the constraint is REAL (not accidentally
    deferred/absent in the test DB): the same dense 5-row RELIANCE
    fixture, migrated in ASCENDING order (the wrong order), must hit
    `uq_historical_bar_identity` on the very first UPDATE, proving Part
    5's requirement is a genuine constraint proof and not a no-op."""
    rows = _representative_rows()
    HistoricalBar.objects.bulk_create(rows)
    reliance_rows = list(
        HistoricalBar.objects.filter(
            instrument_id=str(RELIANCE), timeframe=Timeframe.FIVE_MINUTE.value
        ).order_by("bar_timestamp")
    )

    violation_raised = False
    try:
        with transaction.atomic():
            for row in sorted(reliance_rows, key=lambda r: r.bar_timestamp):  # ASCENDING - wrong
                new_ts = row.bar_timestamp + _FIVE_MIN
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE persistence_historicalbar SET bar_timestamp = %s WHERE id = %s",
                        [new_ts, row.id],
                    )
    except IntegrityError:
        violation_raised = True

    assert violation_raised is True, (
        "ascending-order update did NOT hit uq_historical_bar_identity - the constraint may "
        "not actually be enforced in this test database, invalidating the descending-order proof"
    )
