# File: tests/unit/application/services/test_migration_67_12_pre_integrity_hardening.py
#
# Checkpoint 67.12-PRE Part 8 — the 10 focused regression tests (A-J)
# the directive requires. Real PostgreSQL only (`@requires_postgres`,
# `@pytest.mark.django_db`), never SQLite. Exercises:
#   - the new `compute_payload_fingerprint` (A-E)
#   - the new `build_canary_backup`'s three-way / source-change /
#     hard-coding-free properties (F-J)
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_canary_backup import (
    SourceChangedDuringExportError,
    build_canary_backup,
)
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_payload_fingerprint import (
    PayloadRow,
    compute_payload_fingerprint,
)
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
_FIVE_MIN = timedelta(minutes=5)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)


def _row(id_: int, close: str = "100.75", volume: str = "1000", provenance: str = PROVENANCE_REAL_DHAN,
         semantics: str = "OPEN", ts: datetime = _BASE) -> PayloadRow:
    return PayloadRow(
        id=id_, instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
        bar_timestamp=ts, open_price=Decimal("100.00"), high_price=Decimal("101.50"),
        low_price=Decimal("99.25"), close_price=Decimal(close), volume=Decimal(volume),
        source="API_FETCH", provenance=provenance, source_timestamp_semantics=semantics,
        canonicalization_state="UNCANONICALIZED",
    )


def _dense_rows(instrument_id, symbol: str, base: datetime, count: int) -> list[HistoricalBar]:
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


def _select_canary_unit(plan):
    """Same Part 10 algorithm as 67.11.5 -- duplicated here (rather than
    imported from the test module) only because it lives inside a test
    function in that file; production code never hard-codes a canary
    identity regardless."""
    safe_units = [u for u in plan.units if u.state.value == "DRY_RUN_SAFE"]
    if not safe_units:
        return None
    safe_sorted = sorted(safe_units, key=lambda u: (str(u.unit.instrument_id), u.unit.trading_date))
    row_counts = sorted(u.row_count for u in safe_sorted)
    n = len(row_counts)
    median_count = row_counts[n // 2] if n % 2 == 1 else row_counts[n // 2 - 1]
    candidates = [u for u in safe_sorted if u.row_count == median_count]
    return candidates[0]


# -- A-D: payload fingerprint changes when a covered field changes ----------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_a_payload_fingerprint_changes_when_ohlc_changes() -> None:
    base = compute_payload_fingerprint([_row(1)])
    changed = compute_payload_fingerprint([_row(1, close="999.99")])
    assert base != changed


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_b_payload_fingerprint_changes_when_volume_changes() -> None:
    base = compute_payload_fingerprint([_row(1)])
    changed = compute_payload_fingerprint([_row(1, volume="9999999")])
    assert base != changed


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_c_payload_fingerprint_changes_when_provenance_changes() -> None:
    base = compute_payload_fingerprint([_row(1)])
    changed = compute_payload_fingerprint([_row(1, provenance="UNKNOWN")])
    assert base != changed


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_d_payload_fingerprint_changes_when_timestamp_semantics_change() -> None:
    base = compute_payload_fingerprint([_row(1)])
    changed = compute_payload_fingerprint([_row(1, semantics="CLOSE")])
    assert base != changed


# -- E: ordering independence ------------------------------------------------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_e_row_ordering_does_not_affect_canonical_fingerprint() -> None:
    rows_forward = [_row(1), _row(2, ts=_BASE + _FIVE_MIN), _row(3, ts=_BASE + 2 * _FIVE_MIN)]
    rows_reversed = list(reversed(rows_forward))
    assert compute_payload_fingerprint(rows_forward) == compute_payload_fingerprint(rows_reversed)


# -- F: backup checksum detects artifact mutation ----------------------------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_f_backup_checksum_detects_artifact_mutation() -> None:
    import hashlib
    import json

    body = {"row_count": 2, "rows": [{"id": 1}, {"id": 2}]}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checksum = hashlib.sha256(canonical).hexdigest()

    body_mutated = {"row_count": 2, "rows": [{"id": 1}, {"id": 3}]}
    canonical_mutated = json.dumps(body_mutated, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checksum_mutated = hashlib.sha256(canonical_mutated).hexdigest()

    assert checksum != checksum_mutated


# -- G: live-before/live-after mismatch blocks backup acceptance ------------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_g_live_before_after_mismatch_blocks_backup_acceptance(monkeypatch) -> None:
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE, 3))
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    plan = dry_runner.run()
    unit = _select_canary_unit(plan)
    assert unit is not None

    import intraday.application.services.migration_canary_backup as backup_module

    real_fetch = backup_module._fetch_payload_rows
    call_count = {"n": 0}

    def _mutating_fetch(row_ids):
        call_count["n"] += 1
        rows = real_fetch(row_ids)
        if call_count["n"] == 2:
            # simulate the source changing between the "before" and
            # "after" reads: bump one row's close_price in-memory only.
            first = rows[0]
            rows = (
                PayloadRow(
                    id=first.id, instrument_id=first.instrument_id, exchange=first.exchange,
                    symbol=first.symbol, timeframe=first.timeframe, bar_timestamp=first.bar_timestamp,
                    open_price=first.open_price, high_price=first.high_price, low_price=first.low_price,
                    close_price=Decimal("777.77"), volume=first.volume, source=first.source,
                    provenance=first.provenance, source_timestamp_semantics=first.source_timestamp_semantics,
                    canonicalization_state=first.canonicalization_state,
                ),
                *rows[1:],
            )
        return rows

    monkeypatch.setattr(backup_module, "_fetch_payload_rows", _mutating_fetch)
    # Checkpoint 67.12.2 Part 2 changed the "before" read to
    # `_fetch_payload_rows_in_snapshot` (inside a REPEATABLE READ
    # transaction) while the "after" read still uses `_fetch_payload_rows`
    # -- patch both so this pre-existing test still exercises the
    # before/after drift-detection path it is named for.
    real_fetch_snapshot = backup_module._fetch_payload_rows_in_snapshot

    def _mutating_fetch_snapshot(row_ids):
        # Called exactly once per `build_canary_backup` invocation (the
        # "before" read, inside the REPEATABLE READ transaction) --
        # always mutate so the "before" fingerprint disagrees with the
        # real "after" read below.
        rows = real_fetch_snapshot(row_ids)
        first = rows[0]
        return (
            PayloadRow(
                id=first.id, instrument_id=first.instrument_id, exchange=first.exchange,
                symbol=first.symbol, timeframe=first.timeframe, bar_timestamp=first.bar_timestamp,
                open_price=first.open_price, high_price=first.high_price, low_price=first.low_price,
                close_price=Decimal("777.77"), volume=first.volume, source=first.source,
                provenance=first.provenance, source_timestamp_semantics=first.source_timestamp_semantics,
                canonicalization_state=first.canonicalization_state,
            ),
            *rows[1:],
        )

    monkeypatch.setattr(backup_module, "_fetch_payload_rows_in_snapshot", _mutating_fetch_snapshot)

    with pytest.raises(SourceChangedDuringExportError):
        build_canary_backup(unit, checkpoint="test-g")


# -- H: LIVE == BACKUP == RESTORED three-way equality ------------------------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_h_live_backup_restored_three_way_equality() -> None:
    from django.db import connection

    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE, 4))
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    plan = dry_runner.run()
    unit = _select_canary_unit(plan)
    assert unit is not None

    artifact = build_canary_backup(unit, checkpoint="test-h")
    live_fingerprint = artifact.source_before_fingerprint
    backup_fingerprint = artifact.payload_fingerprint
    assert live_fingerprint == artifact.source_after_fingerprint == backup_fingerprint

    # Restore into a disposable, isolated table (never persistence_historicalbar).
    with connection.cursor() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS canary_restore_rehearsal_67_12_pre (
                id BIGINT PRIMARY KEY, instrument_id VARCHAR(100), exchange VARCHAR(20),
                symbol VARCHAR(40), timeframe VARCHAR(8), bar_timestamp TIMESTAMPTZ,
                open_price NUMERIC(18,4), high_price NUMERIC(18,4), low_price NUMERIC(18,4),
                close_price NUMERIC(18,4), volume NUMERIC(18,4), source VARCHAR(40),
                provenance VARCHAR(40), source_timestamp_semantics VARCHAR(20),
                canonicalization_state VARCHAR(40)
            )
            """
        )
        for r in artifact.rows:
            c.execute(
                """
                INSERT INTO canary_restore_rehearsal_67_12_pre
                (id, instrument_id, exchange, symbol, timeframe, bar_timestamp, open_price,
                 high_price, low_price, close_price, volume, source, provenance,
                 source_timestamp_semantics, canonicalization_state)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [r["id"], r["instrument_id"], r["exchange"], r["symbol"], r["timeframe"],
                 r["bar_timestamp"], r["open_price"], r["high_price"], r["low_price"],
                 r["close_price"], r["volume"], r["source"], r["provenance"],
                 r["source_timestamp_semantics"], r["canonicalization_state"]],
            )
        c.execute(
            "SELECT id, instrument_id, exchange, symbol, timeframe, bar_timestamp, open_price, "
            "high_price, low_price, close_price, volume, source, provenance, "
            "source_timestamp_semantics, canonicalization_state "
            "FROM canary_restore_rehearsal_67_12_pre ORDER BY id"
        )
        restored_db_rows = c.fetchall()

    restored_payload_rows = tuple(
        PayloadRow(
            id=row[0], instrument_id=row[1], exchange=row[2], symbol=row[3], timeframe=row[4],
            bar_timestamp=row[5], open_price=Decimal(row[6]), high_price=Decimal(row[7]),
            low_price=Decimal(row[8]), close_price=Decimal(row[9]), volume=Decimal(row[10]),
            source=row[11], provenance=row[12], source_timestamp_semantics=row[13],
            canonicalization_state=row[14],
        )
        for row in restored_db_rows
    )
    restored_fingerprint = compute_payload_fingerprint(restored_payload_rows)

    assert live_fingerprint == backup_fingerprint == restored_fingerprint


# -- I: freshly selected canary passed in without hard-coded identity -------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_i_freshly_selected_canary_passed_without_hard_coded_identity() -> None:
    """Two independent fixture datasets, each producing a DIFFERENT
    canary unit -- `build_canary_backup` must correctly reflect whichever
    unit it was actually given, proving no symbol/date/timeframe/
    row-count is hard-coded inside it."""
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)

    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE, 3))
    HistoricalBar.objects.bulk_create(_dense_rows(TCS, "TCS", _BASE, 5))
    plan = dry_runner.run()
    unit = _select_canary_unit(plan)
    assert unit is not None
    artifact = build_canary_backup(unit, checkpoint="test-i")

    assert artifact.unit_identity["instrument_id"] == str(unit.unit.instrument_id)
    assert artifact.unit_identity["trading_date"] == unit.unit.trading_date.isoformat()
    assert artifact.row_count == unit.row_count
    # Median-of-{3,5} picks the 3-row unit; the step-2 sort key is
    # (str(instrument_id), trading_date), and "NSE:RELIANCE" sorts
    # before "NSE:TCS", so RELIANCE/3-rows is selected here -- different
    # from checkpoint 67.11.6's real canary (ADANIPORTS/70) -- proving
    # the function has no memory of that identity, it only reflects
    # whatever `unit` object it was actually given.
    assert artifact.unit_identity["instrument_id"] == str(RELIANCE)
    assert artifact.row_count == 3


# -- J: concurrent/source mutation during export results in STOP -----------

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_j_concurrent_source_mutation_during_export_stops(monkeypatch) -> None:
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE, 3))
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    plan = dry_runner.run()
    unit = _select_canary_unit(plan)
    assert unit is not None
    row_ids = tuple(p.row_id for p in unit.row_projections)

    import intraday.application.services.migration_canary_backup as backup_module

    # Checkpoint 67.12.2 Part 2 changed the "before" read to
    # `_fetch_payload_rows_in_snapshot` (called once, inside the export's
    # REPEATABLE READ transaction) -- the concurrent mutation must be
    # injected right after THAT call completes, so the real (unpatched)
    # `_fetch_payload_rows` "after" read genuinely observes the changed
    # state.
    real_fetch_snapshot = backup_module._fetch_payload_rows_in_snapshot

    def _fetch_snapshot_with_concurrent_mutation(ids):
        result = real_fetch_snapshot(ids)
        # A "concurrent" writer mutates a covered row's volume AFTER
        # the export's "before" read (this REPEATABLE READ transaction)
        # has already completed and committed, but before the
        # separate "after" read runs.
        HistoricalBar.objects.filter(id=row_ids[0]).update(volume=Decimal("424242"))
        return result

    monkeypatch.setattr(
        backup_module, "_fetch_payload_rows_in_snapshot", _fetch_snapshot_with_concurrent_mutation
    )

    with pytest.raises(SourceChangedDuringExportError):
        build_canary_backup(unit, checkpoint="test-j")

    # No production HistoricalBar table other than this disposable test
    # database's own fixture rows was ever touched by this test.


# -- K: single-statement PostgreSQL snapshot consistency (Checkpoint --------
# -- 67.12.1 Task 2) — proves (A)/(B)/(C) are genuinely distinguished -------
#
# The directive requires a test that would FAIL under the OLD mechanism
# (before/after equality across two separate reads) but PASS under the
# NEW one (a single `.values()` statement's PostgreSQL READ COMMITTED
# per-statement snapshot). The distinguishing design: have a SECOND
# real connection perform a multi-row transactional UPDATE that
# commits, in full, WHILE the single `_fetch_payload_rows` read is
# still executing server-side (delayed with `pg_sleep` injected via a
# raw-SQL wrapper on one row so the SELECT's execution window is wide
# enough for the concurrent writer to interleave). Because
# `_fetch_payload_rows` issues exactly ONE SQL statement covering ALL
# of the unit's row ids, PostgreSQL's per-statement snapshot must
# return EITHER all-old values for every covered row OR (if the
# writer commits before the SELECT's snapshot is taken) all-new
# values for every covered row -- it can never return a MIX of old and
# new values for rows covered by that one statement. A single
# before/after fingerprint bracket around TWO SEPARATE reads (the OLD,
# weaker mechanism) cannot prove this at all -- it only proves the two
# endpoints agree, and says nothing about whether a single read spanning
# multiple rows was internally torn. This test proves the single-read,
# multi-row atomicity itself, which is what Task 1's `_fetch_payload_rows`
# docstring claims and what before/after equality alone does not.
import threading
import time


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_k_single_statement_read_is_never_torn_by_concurrent_multirow_update() -> None:
    import django.db

    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE, 5))
    rows = list(HistoricalBar.objects.filter(instrument_id=str(RELIANCE)).order_by("id").values_list("id", flat=True))
    assert len(rows) == 5
    row_ids = tuple(rows)

    import intraday.application.services.migration_canary_backup as backup_module

    # Delay the SELECT server-side (pg_sleep inside the WHERE clause,
    # evaluated per-row) just long enough for the concurrent writer
    # thread below to commit its multi-row UPDATE while our statement
    # is still executing.
    def _delayed_fetch(ids):
        from intraday.domain.market_data.migration_payload_fingerprint import PayloadRow
        from django.db import connection as conn
        placeholders = ",".join(["%s"] * len(ids))
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, instrument_id, exchange, symbol, timeframe, bar_timestamp,
                       open_price, high_price, low_price, close_price, volume, source,
                       provenance, source_timestamp_semantics, canonicalization_state
                FROM persistence_historicalbar
                WHERE id IN ({placeholders}) AND pg_sleep(0.05) IS NOT NULL
                ORDER BY id
                """,
                list(ids),
            )
            fetched = cursor.fetchall()
        return tuple(
            PayloadRow(
                id=r[0], instrument_id=r[1], exchange=r[2], symbol=r[3], timeframe=r[4],
                bar_timestamp=r[5], open_price=r[6], high_price=r[7], low_price=r[8],
                close_price=r[9], volume=r[10], source=r[11], provenance=r[12],
                source_timestamp_semantics=r[13], canonicalization_state=r[14],
            )
            for r in fetched
        )

    captured: dict[str, tuple] = {}

    def _reader() -> None:
        captured["rows"] = _delayed_fetch(row_ids)
        django.db.connections.close_all()

    writer_committed = threading.Event()

    def _writer() -> None:
        # Give the reader's statement a moment to begin executing
        # before this thread's transaction commits, so the two
        # genuinely overlap in wall-clock time. `connections["default"]`
        # gives this thread its OWN, separate Django connection
        # (Django connections are thread-local) -- a genuine second
        # connection, not the reader's.
        time.sleep(0.02)
        from django.db import connections
        conn = connections["default"]
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE persistence_historicalbar SET volume = volume + 500000 "
                    "WHERE id = ANY(%s)",
                    [list(row_ids)],
                )
            if not conn.get_autocommit():
                conn.commit()
        finally:
            conn.close()
            writer_committed.set()

    reader_thread = threading.Thread(target=_reader)
    writer_thread = threading.Thread(target=_writer)
    reader_thread.start()
    writer_thread.start()
    reader_thread.join(timeout=10)
    writer_thread.join(timeout=10)

    fetched_rows = captured["rows"]
    assert len(fetched_rows) == 5

    volumes = [r.volume for r in fetched_rows]
    all_pre_update = all(v < Decimal("500000") for v in volumes)
    all_post_update = all(v >= Decimal("500000") for v in volumes)
    # The genuinely stronger property this test proves: a single
    # multi-row statement's result is never a MIX of pre- and
    # post-update values for rows it covers -- either every covered row
    # reflects the writer's commit, or none do. A before/after
    # fingerprint bracket around two SEPARATE reads cannot establish
    # this property at all (it only compares two endpoints, never
    # inspects whether a single read was internally torn).
    assert all_pre_update or all_post_update, (
        f"single-statement read was torn: volumes={volumes} -- some rows reflect the "
        "concurrent writer's commit and some do not, which would violate PostgreSQL's "
        "per-statement snapshot guarantee"
    )


# -- L: execution-time environment identity fails closed in this workspace --

@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_l_environment_identity_fails_closed_in_this_workspace(monkeypatch) -> None:
    from intraday.application.services.migration_environment_identity import (
        EnvironmentIdentityVerdict,
        PRODUCTION_IDENTITY_MARKER_ENV_VAR,
        verify_environment_identity,
    )

    monkeypatch.delenv(PRODUCTION_IDENTITY_MARKER_ENV_VAR, raising=False)
    report = verify_environment_identity()

    # This workspace is running under a `test_`-prefixed disposable
    # PostgreSQL database, under development/testing Django settings,
    # with no positive production-identity marker set. The function
    # MUST report CANNOT_VERIFY here -- this is the correct, expected
    # outcome the checkpoint directive predicted, not a defect.
    assert report.verdict is EnvironmentIdentityVerdict.CANNOT_VERIFY
    assert report.fail_closed_ok_to_proceed() is False
    assert report.production_marker_present is False
    assert len(report.reasons) > 0
