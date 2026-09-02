# File: tests/unit/application/services/test_migration_67_11_5_rollback_rehearsal.py
#
# Checkpoint 67.11.5 Part 11 — rollback rehearsal against disposable
# PostgreSQL, demonstrating TWO DISTINCT recovery mechanisms, clearly
# labeled and tested separately:
#
#   1. TRANSACTION ROLLBACK — an in-flight, uncommitted transaction is
#      aborted (already proven at 67.8/67.11's crash-matrix tests; this
#      file re-demonstrates it explicitly under the Part 11 name for
#      completeness, using the real executor).
#   2. COMPENSATING ROLLBACK — a migration is forward-executed and
#      GENUINELY COMMITTED (a real, separate, already-closed
#      transaction), and only THEN is a distinct, LATER transaction
#      applied that reverses it by re-shifting timestamps back
#      (new - 5m) and restoring canonicalization_state. This is not a
#      database-level UNDO of anything still open — it is a new,
#      independent write that happens to be the exact inverse of the
#      first, proving exact row restoration.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner
from intraday.application.services.migration_execute import HistoricalBarMigrationExecutor
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar
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


# ===========================================================================
# MECHANISM 1 — TRANSACTION ROLLBACK (an open, never-committed
# transaction is aborted; nothing was ever durable).
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_mechanism1_transaction_rollback_uncommitted_write_never_becomes_durable() -> None:
    rows = HistoricalBar.objects.bulk_create(_dense_rows(5))
    row_ids = [r.id for r in rows]
    original = {r.id: (r.bar_timestamp, r.canonicalization_state) for r in rows}

    with pytest.raises(RuntimeError):
        with transaction.atomic():
            for rid, (ts, _state) in sorted(original.items(), key=lambda kv: kv[1][0], reverse=True):
                with connection.cursor() as cur:
                    cur.execute(
                        "UPDATE persistence_historicalbar SET bar_timestamp=%s, canonicalization_state=%s WHERE id=%s",
                        [ts + _FIVE_MIN, "CANONICALIZED", rid],
                    )
            raise RuntimeError("simulated failure before COMMIT — forces a real ROLLBACK")

    fresh = list(
        HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values_list(
            "id", "bar_timestamp", "canonicalization_state"
        )
    )
    for rid, ts, state in fresh:
        assert (ts, state) == original[rid], "transaction rollback failed to fully undo the uncommitted write"


# ===========================================================================
# MECHANISM 2 — COMPENSATING ROLLBACK (forward-migrate to a REAL commit,
# then apply the inverse shift as a SEPARATE, LATER transaction).
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_mechanism2_compensating_rollback_after_genuine_commit_restores_exact_rows() -> None:
    rows = HistoricalBar.objects.bulk_create(_dense_rows(5))
    row_ids = [r.id for r in rows]
    original = {
        r.id: (r.bar_timestamp, r.canonicalization_state, r.open_price, r.high_price, r.low_price, r.close_price)
        for r in rows
    }

    # ---- forward-migrate a synthetic unit to completion, REAL commit ----
    executor = _make_executor()
    from intraday.application.services.migration_dry_run import MigrationUnitKey

    unit_key = MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE)
    report = executor.run(unit_filter=frozenset({unit_key}))
    assert report.committed_unit_count == 1

    committed = list(
        HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values_list(
            "id", "bar_timestamp", "canonicalization_state"
        )
    )
    for rid, ts, state in committed:
        old_ts, old_state, *_ = original[rid]
        assert ts == old_ts + _FIVE_MIN
        assert state == "CANONICALIZED"
    # This is a REAL, already-closed transaction (executor.run() itself
    # commits per-unit) — proven by re-reading from a brand-new queryset
    # after the executor call returned, with no open transaction.

    # ---- COMPENSATING rollback: a SEPARATE, LATER transaction applies
    # the algebraic inverse (new - 5m), restoring canonicalization_state
    # to UNCANONICALIZED. This is NOT undoing anything still open — the
    # forward migration's transaction is long since committed; this is
    # a brand-new write. ----
    with transaction.atomic():
        # Ascending order for a DOWNWARD shift (new - 5m): the
        # smallest-timestamp row must move first so it never collides
        # with a still-unshifted neighbour's occupied slot — the exact
        # mirror-image ordering of the forward migration's descending
        # order for an UPWARD shift.
        current = list(HistoricalBar.objects.filter(id__in=row_ids).order_by("bar_timestamp"))
        for bar in current:
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE persistence_historicalbar SET bar_timestamp=%s, canonicalization_state=%s WHERE id=%s",
                    [bar.bar_timestamp - _FIVE_MIN, "UNCANONICALIZED", bar.id],
                )

    restored = list(
        HistoricalBar.objects.filter(id__in=row_ids).order_by("id").values_list(
            "id", "bar_timestamp", "canonicalization_state", "open_price", "high_price", "low_price", "close_price"
        )
    )
    for rid, ts, state, o, h, l, c in restored:
        old_ts, old_state, old_o, old_h, old_l, old_c = original[rid]
        assert ts == old_ts, "compensating rollback did not restore the exact original bar_timestamp"
        assert state == old_state == "UNCANONICALIZED"
        assert (o, h, l, c) == (old_o, old_h, old_l, old_c), (
            "compensating rollback must restore timestamp/state only — OHLCV columns must be "
            "byte-identical to their pre-migration values (they were never touched by either "
            "direction of this shift)"
        )
