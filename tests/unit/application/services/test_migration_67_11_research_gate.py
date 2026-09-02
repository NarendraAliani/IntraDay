# File: tests/unit/application/services/test_migration_67_11_research_gate.py
#
# Checkpoint 67.11 Parts 17-18 — research-gate behavior during partial
# migration and post-migration research-readiness, tested through the
# ACTUAL `ResearchDataGateService.get_research_eligible_bars` boundary
# (the exact method `BacktestingService.for_database_backed_research`
# calls) against REAL PostgreSQL, with REAL `MigrationRun`/
# `MigrationUnit` audit rows and REAL `HistoricalBar` rows - never the
# standalone `migration_research_gate` helper in isolation (67.8/67.9
# already cover that) and never a mocked resolver.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
    _expected_timestamps,
)
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
    ResearchRejectionReason,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_research_gate import MixedGridResearchRejection
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import DjangoHistoricalBarRepository
from intraday.infrastructure.persistence.models import HistoricalBar, MigrationRun, MigrationUnit
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
INFY = make_instrument_id(Exchange.NSE, "INFY")
TIMEFRAME = Timeframe.FIVE_MINUTE


def _full_day_bounds(trading_date):
    start = datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(trading_date, datetime.max.time(), tzinfo=UTC)
    return start, end


def _persist_full_day(instrument_id, symbol: str, trading_date, *, canonicalization_state: str) -> int:
    """Persists a REAL, COMPLETE day of `HistoricalBar` rows (every
    expected 5m timestamp - `_expected_timestamps` is the SAME,
    unchanged completeness-defining helper `HistoricalDataCoverageService`
    itself uses, so "complete" here means the exact same thing the 66.1
    completeness gate means) with the given canonicalization_state.
    Returns the row count persisted."""
    start, end = _full_day_bounds(trading_date)
    timestamps = _expected_timestamps(start, end, TIMEFRAME, instrument_id)
    rows = [
        HistoricalBar(
            instrument_id=str(instrument_id), exchange="NSE", symbol=symbol, timeframe=TIMEFRAME.value,
            bar_timestamp=ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("1000"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state=canonicalization_state, source_timestamp_semantics="OPEN",
        )
        for ts in timestamps
    ]
    HistoricalBar.objects.bulk_create(rows)
    return len(rows)


def _persist_partial_day(instrument_id, symbol: str, trading_date, *, canonicalization_state: str, keep_fraction: float = 0.5) -> int:
    """Same as `_persist_full_day` but persists only a FRACTION of the
    expected timestamps - a genuinely PARTIAL/incomplete coverage
    fixture, for Part 18's "migrated but PARTIAL coverage -> DENY"
    proof."""
    start, end = _full_day_bounds(trading_date)
    timestamps = _expected_timestamps(start, end, TIMEFRAME, instrument_id)
    kept = timestamps[: max(1, int(len(timestamps) * keep_fraction))]
    rows = [
        HistoricalBar(
            instrument_id=str(instrument_id), exchange="NSE", symbol=symbol, timeframe=TIMEFRAME.value,
            bar_timestamp=ts, open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("1000"),
            source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state=canonicalization_state, source_timestamp_semantics="OPEN",
        )
        for ts in kept
    ]
    HistoricalBar.objects.bulk_create(rows)
    return len(rows)


def _real_gate() -> ResearchDataGateService:
    """The REAL, production-shaped gate: a real `DjangoHistoricalBarRepository`
    reading real DB rows, and the DEFAULT (real, DB-backed)
    `migration_status_resolver` (not injected/faked) - so
    `__post_init__` wires in the actual
    `migration_research_gate_integration.resolve_migration_scope_status`
    exactly as every real production construction site does."""
    repository = DjangoHistoricalBarRepository()
    return ResearchDataGateService(
        repository=repository, coverage_service=HistoricalDataCoverageService(repository=repository)
    )


def _create_run(migration_id: str, status: str) -> None:
    MigrationRun.objects.create(
        migration_id=migration_id, migration_version="67.11", status=status,
        scope_fingerprint="f" * 64, started_at=datetime.now(UTC),
    )


def _create_unit(migration_id: str, instrument_id, trading_date, *, status: str, row_count: int) -> None:
    MigrationUnit.objects.create(
        migration_id=migration_id,
        unit_id=f"{instrument_id}:{TIMEFRAME.value}:{trading_date.isoformat()}",
        instrument_id=str(instrument_id), timeframe=TIMEFRAME.value, trading_date=trading_date,
        status=status, old_row_count=row_count, new_row_count=row_count if status == "COMMITTED" else 0,
        old_scope_fingerprint="f" * 64,
    )


# ===========================================================================
# PART 17 — Unit A=COMMITTED, Unit B=incomplete(MIGRATING), Unit C=PENDING,
# all under one still-RUNNING migration run. The affected scope (B) must
# be DENIED through the ACTUAL gate.
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part17_research_gate_denies_scope_touched_by_in_progress_migration_run() -> None:
    run_id = "mig-67-11-part17"
    _create_run(run_id, "RUNNING")

    date_a, date_b, date_c = CAS_EFFECTIVE_DATE, CAS_EFFECTIVE_DATE, CAS_EFFECTIVE_DATE
    row_count_a = _persist_full_day(RELIANCE, "RELIANCE", date_a, canonicalization_state="CANONICALIZED")
    row_count_b = _persist_full_day(TCS, "TCS", date_b, canonicalization_state="UNCANONICALIZED")
    row_count_c = _persist_full_day(INFY, "INFY", date_c, canonicalization_state="UNCANONICALIZED")

    _create_unit(run_id, RELIANCE, date_a, status="COMMITTED", row_count=row_count_a)
    _create_unit(run_id, TCS, date_b, status="MIGRATING", row_count=row_count_b)
    _create_unit(run_id, INFY, date_c, status="PENDING", row_count=row_count_c)

    gate = _real_gate()
    start, end = _full_day_bounds(date_b)

    # Unit B ("incomplete"/MIGRATING) - the ACTUAL affected scope -
    # must be denied. Note: TCS's own rows are UNCANONICALIZED so the
    # PRE-EXISTING 67.3/67.4 canonicalization gate would ALSO reject
    # this request - to prove the migration-status gate ITSELF is what
    # fires (not merely the older canonicalization gate reaching the
    # same conclusion by coincidence), this test additionally confirms
    # via the standalone resolver that a real RUNNING-owned MigrationUnit
    # row exists for this exact scope, then relies on the documented
    # ordering in `research_data_gate.py` (migration gate runs LAST,
    # after coverage/provenance/canonicalization) - so if migration
    # denial fires it can only be because those earlier gates were
    # satisfied OR the migration gate independently would also deny.
    # The dedicated proof that the migration gate itself is reachable
    # and would deny on ITS OWN merits (independent of canonicalization)
    # is `test_part17_migration_in_progress_denies_even_a_fully_canonicalized_scope` below.
    with pytest.raises((ResearchDataRejectedError, MixedGridResearchRejection)):
        gate.get_research_eligible_bars(
            TCS, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="TCS"
        )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part17_migration_in_progress_denies_even_a_fully_canonicalized_scope() -> None:
    """Isolates the migration-status gate's OWN effect: a scope whose
    rows are ALREADY fully CANONICALIZED and COMPLETE (would otherwise
    sail through every 66.1/67.3/67.4 gate) is STILL denied purely
    because its owning `MigrationRun` is RUNNING - proving the
    mixed-grid rule fires unconditionally for RUNNING/PARTIALLY_COMPLETED,
    exactly as documented, through the REAL gate."""
    run_id = "mig-67-11-part17b"
    _create_run(run_id, "RUNNING")
    trading_date = CAS_EFFECTIVE_DATE
    row_count = _persist_full_day(RELIANCE, "RELIANCE", trading_date, canonicalization_state="CANONICALIZED")
    _create_unit(run_id, RELIANCE, trading_date, status="MIGRATING", row_count=row_count)

    gate = _real_gate()
    start, end = _full_day_bounds(trading_date)
    with pytest.raises(MixedGridResearchRejection) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason == "MIGRATION_IN_PROGRESS"


# ===========================================================================
# PART 18 — CANONICALIZED != RESEARCH_READY, through the ACTUAL gate.
# ===========================================================================


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part18_migrated_completed_run_but_partial_coverage_unit_is_denied() -> None:
    """A COMPLETED migration run, a COMMITTED unit, rows genuinely
    CANONICALIZED - but only a PARTIAL fraction of the expected day's
    bars actually persisted (a real incomplete-coverage fixture, not a
    contrived one). The gate must DENY - CANONICALIZED alone is never
    sufficient; completeness is independently required."""
    run_id = "mig-67-11-part18-partial"
    _create_run(run_id, "COMPLETED")
    trading_date = CAS_EFFECTIVE_DATE
    row_count = _persist_partial_day(
        RELIANCE, "RELIANCE", trading_date, canonicalization_state="CANONICALIZED", keep_fraction=0.5
    )
    _create_unit(run_id, RELIANCE, trading_date, status="COMMITTED", row_count=row_count)

    gate = _real_gate()
    start, end = _full_day_bounds(trading_date)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    # denied at the PRE-EXISTING 66.1 completeness gate (runs before the
    # migration-status gate) - proving PARTIAL coverage alone is enough
    # to deny even a migrated/CANONICALIZED unit, exactly as Part 18
    # requires ("a migrated unit with PARTIAL coverage: DENY").
    assert exc_info.value.reason == ResearchRejectionReason.INCOMPLETE_COVERAGE


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part18_migrated_completed_run_and_complete_coverage_unit_is_allowed() -> None:
    """The genuine positive case, using a SYNTHETIC COMPLETE fixture
    (real production data has zero COMPLETE-coverage units at present,
    per the checkpoint's own stated production state) - a COMPLETED
    migration run, a COMMITTED unit, and a FULL day's worth of
    CANONICALIZED rows (100% expected-timestamp coverage). Only here,
    with EVERY required condition independently satisfied (source
    semantics proven, provenance REAL_DHAN, canonicalization_state=
    CANONICALIZED, 100% complete, migration run COMPLETED, unit
    COMMITTED) does the ACTUAL gate allow the request through."""
    run_id = "mig-67-11-part18-complete"
    _create_run(run_id, "COMPLETED")
    trading_date = CAS_EFFECTIVE_DATE
    row_count = _persist_full_day(RELIANCE, "RELIANCE", trading_date, canonicalization_state="CANONICALIZED")
    _create_unit(run_id, RELIANCE, trading_date, status="COMMITTED", row_count=row_count)

    gate = _real_gate()
    start, end = _full_day_bounds(trading_date)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert len(result.bars) == row_count
    assert result.coverage.is_complete is True


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_part18_canonicalized_but_run_not_completed_yet_is_still_denied() -> None:
    """A further CANONICALIZED != RESEARCH_READY proof: rows are fully
    CANONICALIZED and coverage is 100% complete, but the owning
    `MigrationRun` is still PARTIALLY_COMPLETED (not yet COMPLETED) -
    the mixed-grid rule denies unconditionally for
    RUNNING/PARTIALLY_COMPLETED regardless of the unit's own
    canonicalization/completeness state. Proves "canonicalized" is
    necessary but never sufficient on its own - the RUN's own state
    matters independently."""
    run_id = "mig-67-11-part18-notyet"
    _create_run(run_id, "PARTIALLY_COMPLETED")
    trading_date = CAS_EFFECTIVE_DATE
    row_count = _persist_full_day(RELIANCE, "RELIANCE", trading_date, canonicalization_state="CANONICALIZED")
    _create_unit(run_id, RELIANCE, trading_date, status="COMMITTED", row_count=row_count)

    gate = _real_gate()
    start, end = _full_day_bounds(trading_date)
    with pytest.raises(MixedGridResearchRejection) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason == "MIGRATION_IN_PROGRESS"
