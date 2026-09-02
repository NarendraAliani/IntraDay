# File: tests/unit/application/services/test_migration_67_11_5_connection_drop.py
#
# Checkpoint 67.11.5 Part 4 — a GENUINE forcibly-terminated database
# connection test, going strictly further than 67.11's deterministic
# Python-exception injection (`test_migration_67_11_stress.py`'s
# `_InjectedCrash` matrix, which proved transaction-atomicity logic but
# never actually severed a socket).
#
# Mechanism (real, not simulated):
#   1. Open a RAW psycopg connection (not Django's ORM connection) at
#      the SAME disposable-Postgres test database Django's own
#      connection is pointed at (`connection.settings_dict`).
#   2. `BEGIN` a transaction on that raw connection and issue a real
#      `UPDATE persistence_historicalbar ...` against real fixture
#      rows, using the SAME SQL shape `HistoricalBarMigrationExecutor.
#      _execute_unit` issues.
#   3. Call `raw_conn.close()` — a REAL, OS-level termination of that
#      connection's underlying socket — WITHOUT ever issuing COMMIT.
#      This is not a Python exception caught by a `try/except`; it is
#      the same "the process holding the connection died" event a
#      genuine crash/kill -9/network partition produces from
#      PostgreSQL's point of view: the server-side backend detects the
#      severed socket and unilaterally aborts the in-flight transaction
#      itself (Postgres's own crash-safety, not this codebase's).
#   4. From a FRESH connection/cursor (a brand-new raw psycopg
#      connection, standing in for "a genuinely fresh process"),
#      inspect `HistoricalBar` + the `MigrationUnit` audit table and
#      prove NOTHING committed — no partial write survived.
#   5. Invoke the REAL production `resume_migration_run` (imported from
#      `migration_execute.py`, not a test-local copy — Checkpoint
#      67.11.5 Part 1) and prove it correctly reconciles the abandoned
#      unit and completes the migration cleanly.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from django.db import connection

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import (
    MIGRATION_ID,
    HistoricalBarMigrationDryRunner,
    MigrationUnitKey,
)
from intraday.application.services.migration_execute import (
    HistoricalBarMigrationExecutor,
    reconcile_abandoned_unit,
    resume_migration_run,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar, MigrationUnit
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
_FIVE_MIN = timedelta(minutes=5)
_TRADING_DATE = date(2026, 8, 10)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)


def _dense_rows(count: int = 5) -> list[HistoricalBar]:
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


def _raw_psycopg_connect() -> psycopg.Connection:
    """A brand-new, independent raw connection to the SAME disposable
    Postgres test database Django's own ORM connection is pointed at —
    a genuinely separate backend/session on the server side, not the
    Django connection object."""
    settings = connection.settings_dict
    return psycopg.connect(
        host=settings.get("HOST") or "localhost",
        port=settings.get("PORT") or 5432,
        dbname=settings["NAME"],
        user=settings.get("USER"),
        password=settings.get("PASSWORD"),
        connect_timeout=5,
        autocommit=False,
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part4_real_connection_termination_leaves_no_partial_commit_then_production_resume_reconciles() -> None:
    rows = HistoricalBar.objects.bulk_create(_dense_rows(5))
    row_ids = [r.id for r in rows]
    original_ts = {r.id: r.bar_timestamp for r in rows}

    # ---- Step 1/2: raw connection, BEGIN, real UPDATE, no COMMIT ----
    raw_conn = _raw_psycopg_connect()
    try:
        # Descending bar_timestamp order — the same collision-avoidance
        # ordering `HistoricalBarMigrationExecutor._execute_unit` uses
        # (each +5m shift must never collide with the next row's
        # still-unshifted slot mid-sequence).
        with raw_conn.cursor() as cur:
            for rid, ts in sorted(original_ts.items(), key=lambda kv: kv[1], reverse=True):
                new_ts = ts + _FIVE_MIN
                cur.execute(
                    """
                    UPDATE persistence_historicalbar
                    SET bar_timestamp = %s, canonicalization_state = %s
                    WHERE id = %s
                    """,
                    [new_ts, "CANONICALIZED", rid],
                )
        # Sanity: within the SAME still-open raw transaction, the
        # UPDATE is visible to itself (proves the UPDATE really
        # executed).
        with raw_conn.cursor() as cur:
            cur.execute(
                "SELECT canonicalization_state FROM persistence_historicalbar WHERE id = ANY(%s)",
                [row_ids],
            )
            in_txn_states = {r[0] for r in cur.fetchall()}
        assert in_txn_states == {"CANONICALIZED"}, "the UPDATE did not actually execute inside the raw transaction"
    finally:
        # ---- Step 3: REAL, forcible termination — no COMMIT ever
        # issued ---- OS-level socket close; PostgreSQL's own backend
        # detects the dropped connection and unilaterally rolls back
        # the open transaction — this is Postgres crash-safety, not
        # Python exception handling. Runs even if the sanity assertion
        # above fails, so no connection is ever leaked into teardown.
        raw_conn.close()

    # ---- Step 4: FRESH connection/cursor, prove zero partial commit ----
    fresh_conn = _raw_psycopg_connect()
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(
                "SELECT id, bar_timestamp, canonicalization_state FROM persistence_historicalbar "
                "WHERE id = ANY(%s) ORDER BY id",
                [row_ids],
            )
            fresh_rows = cur.fetchall()
    finally:
        fresh_conn.close()

    assert len(fresh_rows) == 5
    for rid, ts, state in fresh_rows:
        normalized_ts = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        assert normalized_ts == original_ts[rid], (
            f"row {rid} survived the terminated connection's UPDATE — real Postgres did not roll it back"
        )
        assert state == "UNCANONICALIZED", (
            f"row {rid} shows {state!r} after the connection was forcibly closed without COMMIT — "
            "a genuine partial commit survived, which must never happen"
        )

    # Also confirm through Django's own (separate) connection/ORM — a
    # second, independent verification path.
    django_fresh = list(
        HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values_list(
            "id", "bar_timestamp", "canonicalization_state"
        )
    )
    assert all(state == "UNCANONICALIZED" for _id, _ts, state in django_fresh)
    assert all(ts == original_ts[rid] for rid, ts, _state in django_fresh)

    # No MigrationUnit audit row exists — the terminated raw connection
    # never ran through the executor, so there is no control-plane
    # record at all for this unit; exactly the "gap" scenario resume
    # must reconcile from data-plane state alone.
    assert MigrationUnit.objects.filter(instrument_id=str(RELIANCE)).count() == 0

    # ---- reconciliation must classify this as UNMODIFIED, not guess ----
    verdict = reconcile_abandoned_unit(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE,
        migration_id=MIGRATION_ID,
    )
    assert verdict == "UNMODIFIED"

    # ---- Step 5: the REAL production resume function completes it ----
    executor = _make_executor()
    unit_key = MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE)
    resume_report = resume_migration_run(
        executor=executor,
        migration_id=MIGRATION_ID,
        candidate_units=frozenset({unit_key}),
    )
    assert resume_report is not None
    assert resume_report.committed_unit_count == 1

    final_rows = list(HistoricalBar.objects.filter(id__in=row_ids).order_by("id"))
    assert all(r.canonicalization_state == "CANONICALIZED" for r in final_rows)
    assert all(r.bar_timestamp == original_ts[r.id] + _FIVE_MIN for r in final_rows)
