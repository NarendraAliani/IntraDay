# File: tests/unit/infrastructure/persistence/test_checkpoint_67_9_bulk_upsert_lock_ordering.py
#
# Checkpoint 67.9 Part 1 — proof against the ACTUAL
# `DjangoHistoricalBarRepository.bulk_upsert()` method (not a bare
# `pg_try_advisory_xact_lock` stand-in, which is what 67.8's own
# `test_bulk_upsert_and_migration_lock_serialize_for_same_instrument_
# timeframe` used). Connection A holds the real migration advisory lock
# for (RELIANCE, 5m) inside an open transaction; Connection B calls the
# real `bulk_upsert()` for the SAME scope on a SEPARATE thread/
# connection and must observably block until A releases, then complete
# and persist its row. A second test proves a DIFFERENT scope
# (INFY, 5m) is not blocked by A's held lock.
#
# Checkpoint 67.9 Part 2 — deterministic multi-lock ordering / deadlock
# avoidance. `bulk_upsert()` now sorts its per-(instrument,timeframe)
# groups by canonical lock key before acquiring
# (`historical_bar_repository.py`, "DETERMINISTIC LOCK ORDERING").
# Proven here with two threads issuing `bulk_upsert()` calls that
# contain the SAME two groups (RELIANCE/5m, INFY/5m) in OPPOSITE input
# order, both racing concurrently — with a Postgres `lock_timeout` set
# so that if the ordering fix were absent and a real deadlock cycle
# formed, the test would observably time out / raise rather than hang
# forever, and with an assertion that BOTH calls complete successfully
# (proving no deadlock occurred at all — the primary defense here is
# the canonical ordering itself, not PostgreSQL's deadlock detector;
# the `lock_timeout` is a secondary/observability safety net making a
# regression fail loudly and fast instead of hanging the test suite).
from __future__ import annotations

import threading
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import connection, connections, transaction

from intraday.application.services.migration_advisory_lock import (
    historical_migration_lock_key,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
INFY = make_instrument_id(Exchange.NSE, "INFY")
_TS = datetime(2026, 1, 5, 9, 20, tzinfo=dt_timezone.utc)


def _bar(instrument_id, ts=_TS) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=ts,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.50"),
        volume=Decimal("1000"),
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_actual_bulk_upsert_blocks_on_same_scope_migration_lock_then_completes() -> None:
    """Connection A: BEGIN, acquire migration lock for (RELIANCE, 5m),
    hold. Connection B: call the REAL `DjangoHistoricalBarRepository.
    bulk_upsert()` for (RELIANCE, 5m) on its own thread/connection.
    Assert B has NOT completed while A holds the lock; release A;
    assert B completes and the row is persisted."""
    key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    a_acquired = threading.Event()
    release_a = threading.Event()

    def _hold_lock_on_connection_a() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                a_acquired.set()
                release_a.wait(timeout=10)
        finally:
            connections.close_all()

    thread_a = threading.Thread(target=_hold_lock_on_connection_a)
    thread_a.start()
    assert a_acquired.wait(timeout=10), "connection A never signalled lock acquisition"

    b_done = threading.Event()
    b_result: dict[str, int] = {}

    def _call_real_bulk_upsert_on_connection_b() -> None:
        try:
            repo = DjangoHistoricalBarRepository()
            written = repo.bulk_upsert(
                (_bar(RELIANCE),), source="API_FETCH", provenance="REAL_DHAN"
            )
            b_result["written"] = written
        finally:
            b_done.set()
            connections.close_all()

    thread_b = threading.Thread(target=_call_real_bulk_upsert_on_connection_b)
    thread_b.start()
    try:
        # B must NOT complete while A holds the same-scope lock.
        blocked_while_a_holds = not b_done.wait(timeout=1.5)
        assert blocked_while_a_holds, (
            "the REAL bulk_upsert() call completed while a same-scope migration lock was "
            "held elsewhere - it did not actually block"
        )
    finally:
        release_a.set()
        thread_a.join(timeout=10)

    assert b_done.wait(timeout=10), "bulk_upsert() never completed after the lock was released"
    thread_b.join(timeout=10)
    assert b_result.get("written") == 1

    persisted = HistoricalBar.objects.filter(
        instrument_id=str(RELIANCE), timeframe=Timeframe.FIVE_MINUTE.value, bar_timestamp=_TS
    )
    assert persisted.count() == 1


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_actual_bulk_upsert_not_blocked_by_different_scope_lock() -> None:
    """A holds the migration lock for (RELIANCE, 5m); a REAL
    `bulk_upsert()` call for the DIFFERENT scope (INFY, 5m) must
    complete promptly without waiting for A."""
    key = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    a_acquired = threading.Event()
    release_a = threading.Event()

    def _hold_lock_on_connection_a() -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
                a_acquired.set()
                release_a.wait(timeout=10)
        finally:
            connections.close_all()

    thread_a = threading.Thread(target=_hold_lock_on_connection_a)
    thread_a.start()
    try:
        assert a_acquired.wait(timeout=10)
        repo = DjangoHistoricalBarRepository()
        written = repo.bulk_upsert((_bar(INFY),), source="API_FETCH", provenance="REAL_DHAN")
        assert written == 1
    finally:
        release_a.set()
        thread_a.join(timeout=10)

    assert HistoricalBar.objects.filter(
        instrument_id=str(INFY), timeframe=Timeframe.FIVE_MINUTE.value, bar_timestamp=_TS
    ).count() == 1


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_multi_group_bulk_upsert_opposite_input_order_does_not_deadlock() -> None:
    """Two threads each call the REAL `bulk_upsert()` with bars for BOTH
    (RELIANCE, 5m) and (INFY, 5m) in a single call, but built from
    input tuples in OPPOSITE order (thread 1: RELIANCE-then-INFY bars;
    thread 2: INFY-then-RELIANCE bars). Before Part 2's fix, if a
    single `bulk_upsert()` call could hold multiple locks
    simultaneously in input order, this shape is the classic
    A-locks-X-waits-Y / B-locks-Y-waits-X deadlock. With canonical
    lock-key ordering, both threads acquire in the SAME order
    regardless of input order, so no cycle can form. A conservative
    `lock_timeout` is set so a regression fails fast/loud instead of
    hanging the suite."""
    ts_2 = _TS.replace(minute=25)

    def _run(order: str, result: dict, exc: dict) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            repo = DjangoHistoricalBarRepository()
            if order == "reliance_first":
                bars = (_bar(RELIANCE, ts_2), _bar(INFY, ts_2))
            else:
                bars = (_bar(INFY, ts_2), _bar(RELIANCE, ts_2))
            result["written"] = repo.bulk_upsert(bars, source="API_FETCH", provenance="REAL_DHAN")
        except Exception as e:  # noqa: BLE001 - captured for assertion, not swallowed
            exc["error"] = e
        finally:
            connections.close_all()

    result_1: dict = {}
    result_2: dict = {}
    exc_1: dict = {}
    exc_2: dict = {}
    t1 = threading.Thread(target=_run, args=("reliance_first", result_1, exc_1))
    t2 = threading.Thread(target=_run, args=("infy_first", result_2, exc_2))
    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)

    assert not t1.is_alive() and not t2.is_alive(), "a bulk_upsert() call hung - possible deadlock"
    assert exc_1 == {}, f"thread 1 (RELIANCE-first) raised: {exc_1.get('error')!r}"
    assert exc_2 == {}, f"thread 2 (INFY-first) raised: {exc_2.get('error')!r}"
    assert result_1.get("written") == 2
    assert result_2.get("written") == 2

    for instrument_id in (RELIANCE, INFY):
        assert HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=Timeframe.FIVE_MINUTE.value,
            bar_timestamp=ts_2,
        ).count() == 1
