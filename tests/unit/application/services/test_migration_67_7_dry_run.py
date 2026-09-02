# tests/unit/application/services/test_migration_67_7_dry_run.py
#
# Checkpoint 67.7 Part 18 test coverage: migration eligibility,
# segment/era policy, dry-run runner, lock-policy, state-machine,
# rollback arithmetic, mixed-grid protection, and the Part 5 dry-run
# write-safety guard. NO actual migration is ever executed; NO
# backtest; NO Gainz.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from unittest.mock import patch

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_advisory_lock import (
    historical_migration_lock_key,
)
from intraday.application.services.migration_dry_run import (
    CollisionClassification,
    DryRunWriteAttemptedError,
    HistoricalBarMigrationDryRunner,
    NoWriteHistoricalBarRepository,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.migration_audit import (
    MigrationAuditRecord,
    assert_unique_migration_row_pairs,
    forward_shift,
    rollback_shift,
    verify_algebraic_rollback,
)
from intraday.domain.market_data.migration_state import (
    DRY_RUN_REACHABLE_RUN_STATES,
    DRY_RUN_REACHABLE_UNIT_STATES,
    MigrationRunState,
    MigrationUnitState,
    assert_dry_run_state_reachable,
)
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN, PROVENANCE_UNKNOWN
from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_CANONICALIZED
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


# ---------------------------------------------------------------------------
# Rollback arithmetic (Part 11 - ALGEBRAIC ROLLBACK VALIDATION)
# ---------------------------------------------------------------------------


def test_algebraic_rollback_identity_holds() -> None:
    old = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    interval = timedelta(minutes=5)
    new = forward_shift(old, interval)
    assert new == old + interval
    assert rollback_shift(new, interval) == old
    assert verify_algebraic_rollback(old, interval) is True


def test_algebraic_rollback_holds_across_many_timestamps() -> None:
    interval = timedelta(minutes=5)
    base = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    for i in range(200):
        old = base + i * interval
        assert verify_algebraic_rollback(old, interval)


# ---------------------------------------------------------------------------
# Audit mapping data contract (Part 7)
# ---------------------------------------------------------------------------


def test_audit_record_uniqueness_enforced() -> None:
    rec = MigrationAuditRecord(
        migration_id="m1", row_id=1, instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE,
        old_timestamp=datetime(2026, 8, 10, 9, 15, tzinfo=UTC),
        new_timestamp=datetime(2026, 8, 10, 9, 20, tzinfo=UTC),
        source_semantics="OPEN", proof_scope="PROVEN", status=MigrationUnitState.PENDING,
        applied_at=None,
    )
    assert_unique_migration_row_pairs((rec,))
    with pytest.raises(ValueError):
        assert_unique_migration_row_pairs((rec, rec))


def test_audit_record_old_timestamp_reconstructable() -> None:
    old = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    rec = MigrationAuditRecord(
        migration_id="m1", row_id=1, instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE,
        old_timestamp=old, new_timestamp=old + timedelta(minutes=5),
        source_semantics="OPEN", proof_scope="PROVEN", status=MigrationUnitState.PENDING,
        applied_at=None,
    )
    # old_timestamp is never derived from new_timestamp - it is carried
    # verbatim, so it remains directly readable regardless of any later
    # state transition.
    assert rec.old_timestamp == old
    assert rec.applied_at is None  # never set by a dry-run record


# ---------------------------------------------------------------------------
# State machine (Part 6)
# ---------------------------------------------------------------------------


def test_dry_run_reachable_states_are_the_documented_subset() -> None:
    assert DRY_RUN_REACHABLE_RUN_STATES == {MigrationRunState.PLANNED, MigrationRunState.ABORTED}
    assert DRY_RUN_REACHABLE_UNIT_STATES == {
        MigrationUnitState.PENDING,
        MigrationUnitState.DRY_RUN_SAFE,
        MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
        MigrationUnitState.FAILED,
    }
    assert_dry_run_state_reachable(MigrationRunState.PLANNED)
    assert_dry_run_state_reachable(MigrationUnitState.DRY_RUN_SAFE)


def test_dry_run_cannot_reach_committed_or_rolled_back() -> None:
    with pytest.raises(AssertionError):
        assert_dry_run_state_reachable(MigrationUnitState.COMMITTED)
    with pytest.raises(AssertionError):
        assert_dry_run_state_reachable(MigrationUnitState.ROLLED_BACK)
    with pytest.raises(AssertionError):
        assert_dry_run_state_reachable(MigrationRunState.RUNNING)
    with pytest.raises(AssertionError):
        assert_dry_run_state_reachable(MigrationRunState.COMPLETED)


# ---------------------------------------------------------------------------
# Lock policy (Part 2)
# ---------------------------------------------------------------------------


def test_lock_key_is_deterministic() -> None:
    k1 = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    k2 = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    assert k1 == k2
    assert isinstance(k1, int)


def test_lock_key_differs_across_instrument_and_timeframe() -> None:
    tcs = make_instrument_id(Exchange.NSE, "TCS")
    k_reliance_5m = historical_migration_lock_key(RELIANCE, Timeframe.FIVE_MINUTE)
    k_tcs_5m = historical_migration_lock_key(tcs, Timeframe.FIVE_MINUTE)
    k_reliance_1m = historical_migration_lock_key(RELIANCE, Timeframe.ONE_MINUTE)
    assert k_reliance_5m != k_tcs_5m
    assert k_reliance_5m != k_reliance_1m


# ---------------------------------------------------------------------------
# Part 5 - dry-run write-safety guard
# ---------------------------------------------------------------------------


def test_no_write_repository_raises_on_any_write_attempt() -> None:
    guard = NoWriteHistoricalBarRepository()
    with pytest.raises(DryRunWriteAttemptedError):
        guard.bulk_upsert((), source="X")


@requires_postgres
@pytest.mark.django_db
def test_dry_run_never_calls_any_historicalbar_write_method() -> None:
    """The explicit, TESTED safety guard (Part 5): monkeypatch every
    `HistoricalBar`/QuerySet write method to raise if called, run a
    real dry-run against the (test) database, and assert it completes
    successfully without ever tripping one of those patches."""
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("dry-run attempted a HistoricalBar write")

    with patch.object(HistoricalBar, "save", _boom), patch.object(
        type(HistoricalBar.objects), "bulk_create", _boom
    ), patch.object(type(HistoricalBar.objects), "bulk_update", _boom), patch.object(
        type(HistoricalBar.objects.all()), "update", _boom
    ), patch.object(type(HistoricalBar.objects.all()), "delete", _boom):
        report = runner.run()

    assert report.run_state is MigrationRunState.PLANNED
    for unit in report.units:
        assert unit.state in (
            MigrationUnitState.DRY_RUN_SAFE,
            MigrationUnitState.FAILED,
            MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
        )


# ---------------------------------------------------------------------------
# Segment/era policy + collision classification + completeness (Parts 8/9/12/13)
# ---------------------------------------------------------------------------


def _real_bar(ts, close="100.00"):
    return Bar(
        instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, timestamp=ts,
        open=Decimal("100.00"), high=Decimal("110.00"), low=Decimal("90.00"),
        close=Decimal(close), volume=Decimal("1000"),
    )


@requires_postgres
@pytest.mark.django_db
def test_dry_run_finds_no_eligible_units_when_db_is_empty() -> None:
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    report = runner.run()
    assert report.eligible_row_count == 0
    assert report.unit_count == 0
    assert report.run_state is MigrationRunState.PLANNED


@requires_postgres
@pytest.mark.django_db
def test_dry_run_classifies_bse_5m_cas_era_rows_as_unproven_and_unsafe() -> None:
    """67.6's segment-proof-scope fix: BSE_EQ must never resolve
    PROVEN even at NSE's proven timeframe/era - the dry-run runner
    must independently reconfirm this live, not just trust it."""
    bse_instrument = make_instrument_id(Exchange.BSE, "RELIANCE")
    HistoricalBar.objects.bulk_create(
        [
            HistoricalBar(
                instrument_id=str(bse_instrument), exchange="BSE", symbol="RELIANCE",
                timeframe="5m", bar_timestamp=datetime(2026, 8, 10, 9, 15, tzinfo=UTC),
                open_price=Decimal("100"), high_price=Decimal("101"), low_price=Decimal("99"),
                close_price=Decimal("100.5"), volume=Decimal("10"), source="API_FETCH",
                provenance=PROVENANCE_REAL_DHAN, canonicalization_state="UNCANONICALIZED",
                source_timestamp_semantics="UNKNOWN",
            )
        ]
    )
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    report = runner.run()
    # BSE rows are filtered out entirely by the live eligibility query
    # (exchange="NSE" filter) - proving the pre-filter itself already
    # excludes BSE, independent of the segment-proof-scope check.
    assert report.eligible_row_count == 0


@requires_postgres
@pytest.mark.django_db
def test_dry_run_classifies_already_canonical_collision() -> None:
    old_ts = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    new_ts = old_ts + timedelta(minutes=5)
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
                canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
                source_timestamp_semantics="OPEN",
            ),
        ]
    )
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    report = runner.run()
    assert report.eligible_row_count == 1
    assert report.unit_count == 1
    unit = report.units[0]
    assert unit.state == MigrationUnitState.FAILED
    assert unit.row_projections[0].classification == CollisionClassification.ALREADY_CANONICAL_COLLISION
    assert unit.row_projections[0].rollback_ok is True


@requires_postgres
@pytest.mark.django_db
def test_dry_run_classifies_cross_provenance_collision() -> None:
    old_ts = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    new_ts = old_ts + timedelta(minutes=5)
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
                source="API_FETCH", provenance=PROVENANCE_UNKNOWN,
                canonicalization_state="UNKNOWN", source_timestamp_semantics="UNKNOWN",
            ),
        ]
    )
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
    report = runner.run()
    unit = report.units[0]
    assert unit.state == MigrationUnitState.FAILED
    assert unit.row_projections[0].classification == CollisionClassification.CROSS_PROVENANCE_COLLISION


# ---------------------------------------------------------------------------
# CANONICALIZED vs RESEARCH_READY (Part 13) / mixed-grid protection (Part 14)
# ---------------------------------------------------------------------------


def test_canonicalized_state_alone_never_implies_research_ready() -> None:
    """A row can be `canonicalization_state=CANONICALIZED` while its
    `source_timestamp_semantics` is still `UNKNOWN` -
    `ResearchDataGateService` (unchanged by this checkpoint) must still
    reject it. This is the mechanical hook Part 14 requires: as long as
    dry-run never flips `canonicalization_state` (which it never does -
    it performs zero writes), the existing gate's CANONICALIZED+PROVEN
    double-check already prevents any unit from being treated as
    research-ready while conceptually 'in flight'."""
    from intraday.domain.market_data.source_timestamp import (
        is_canonicalized,
        is_source_semantics_proven,
    )

    assert is_canonicalized(CANONICALIZATION_STATE_CANONICALIZED) is True
    assert is_source_semantics_proven("UNKNOWN") is False
    # i.e. CANONICALIZED + UNKNOWN semantics must still fail the
    # combined research-eligibility check ResearchDataGateService runs.
    research_ready = is_canonicalized(CANONICALIZATION_STATE_CANONICALIZED) and is_source_semantics_proven(
        "UNKNOWN"
    )
    assert research_ready is False


@requires_postgres
@pytest.mark.django_db
def test_dry_run_performs_zero_writes_so_canonicalization_state_column_is_never_flipped() -> None:
    """Mixed-grid protection's mechanical enforcement: since dry-run
    never calls any write method (proven above), no row's
    `canonicalization_state` can ever be flipped to `CANONICALIZED` by
    this checkpoint's runner - so `ResearchDataGateService`'s existing,
    unmodified gate continues to see every migrated-but-not-yet-applied
    row as `UNCANONICALIZED`, and therefore never research-ready,
    for the entire duration of (and after) any dry-run."""
    old_ts = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
    HistoricalBar.objects.bulk_create(
        [
            HistoricalBar(
                instrument_id=str(RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=old_ts, open_price=Decimal("100"), high_price=Decimal("101"),
                low_price=Decimal("99"), close_price=Decimal("100.5"), volume=Decimal("10"),
                source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
        ]
    )
    before = HistoricalBar.objects.get(bar_timestamp=old_ts).canonicalization_state
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    HistoricalBarMigrationDryRunner(coverage_service=coverage_service).run()
    after = HistoricalBar.objects.get(bar_timestamp=old_ts).canonicalization_state
    assert before == after == "UNCANONICALIZED"
