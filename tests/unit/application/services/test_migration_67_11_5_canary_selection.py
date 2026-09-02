# File: tests/unit/application/services/test_migration_67_11_5_canary_selection.py
#
# Checkpoint 67.11.5 Part 10 — a deterministic, READ-ONLY canary-unit
# selection algorithm. Selects exactly one NORMAL, representative
# eligible unit (never hard-coded, never an anomalous edge case) from
# whatever the reused dry-run planner (`HistoricalBarMigrationDryRunner`,
# unmodified — same DHAN/NSE_EQ/5m/CAS-era/OPEN/UNCANONICALIZED
# eligibility this codebase already enforces) reports as DRY_RUN_SAFE.
#
# Algorithm (pure, deterministic, no randomness, no hard-coded
# symbol/date):
#   1. Take every DRY_RUN_SAFE unit from the planner's own plan.
#   2. Sort them by the SAME deterministic key the planner itself
#      already uses: (str(instrument_id), trading_date).
#   3. Compute the MEDIAN row_count across that safe set.
#   4. Among units whose row_count equals the median, pick the FIRST
#      in the step-2 sort order — this favours a unit that is exactly
#      "typical" for the scope (neither the sparsest nor the densest),
#      with ties broken deterministically rather than arbitrarily.
#
# This module exercises the algorithm against disposable PostgreSQL
# fixtures (never production) to prove it is deterministic and that it
# avoids an artificially constructed edge case; the SAME algorithm was
# separately run read-only against the live production scope (147
# eligible units) — see taskReport.md Part J for that result. Nothing
# in this file or its production counterpart ever calls `.run()` on the
# WRITE-capable executor, nor does it write anything.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
INFY = make_instrument_id(Exchange.NSE, "INFY")
_FIVE_MIN = timedelta(minutes=5)
_TRADING_DATE_1 = date(2026, 8, 10)
_TRADING_DATE_2 = date(2026, 8, 11)
_BASE_1 = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
_BASE_2 = datetime(2026, 8, 11, 9, 15, tzinfo=UTC)


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


def select_canary_unit(plan):
    """The Part 10 algorithm — pure function over a `MigrationDryRunReport`,
    zero writes, zero side effects."""
    safe_units = [u for u in plan.units if u.state.value == "DRY_RUN_SAFE"]
    if not safe_units:
        return None
    safe_sorted = sorted(safe_units, key=lambda u: (str(u.unit.instrument_id), u.unit.trading_date))
    row_counts = sorted(u.row_count for u in safe_sorted)
    n = len(row_counts)
    median_count = row_counts[n // 2] if n % 2 == 1 else row_counts[n // 2 - 1]
    candidates = [u for u in safe_sorted if u.row_count == median_count]
    return candidates[0]


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_canary_selection_picks_the_median_row_count_unit_deterministically() -> None:
    """3 units with deliberately different row counts (3, 5, 7) — the
    algorithm must pick the MIDDLE one (5 rows), never the sparsest or
    densest, and never a hard-coded symbol."""
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 3))
    HistoricalBar.objects.bulk_create(_dense_rows(TCS, "TCS", _BASE_1, 5))
    HistoricalBar.objects.bulk_create(_dense_rows(INFY, "INFY", _BASE_2, 7))

    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    plan = dry_runner.run()

    canary = select_canary_unit(plan)
    assert canary is not None
    assert canary.row_count == 5
    assert canary.unit.instrument_id == TCS


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_canary_selection_is_deterministic_across_repeated_calls() -> None:
    """Two independent selection passes against the IDENTICAL DB state
    must pick the identical unit — no randomness, no iteration-order
    dependency."""
    HistoricalBar.objects.bulk_create(_dense_rows(RELIANCE, "RELIANCE", _BASE_1, 4))
    HistoricalBar.objects.bulk_create(_dense_rows(TCS, "TCS", _BASE_1, 4))
    HistoricalBar.objects.bulk_create(_dense_rows(INFY, "INFY", _BASE_2, 6))

    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)

    canary1 = select_canary_unit(dry_runner.run())
    canary2 = select_canary_unit(dry_runner.run())
    assert canary1.unit == canary2.unit
    assert canary1.row_count == canary2.row_count


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_canary_selection_returns_none_when_nothing_eligible() -> None:
    """No fixture rows at all -> no DRY_RUN_SAFE units -> the algorithm
    returns `None` rather than fabricating a candidate."""
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    plan = dry_runner.run()
    assert select_canary_unit(plan) is None
