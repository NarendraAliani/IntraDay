# File: tests/unit/application/services/test_checkpoint_67_9_research_gate_migration_wiring.py
#
# Checkpoint 67.9 Part 8-9 — proves the mixed-grid migration-status
# check is wired into the ACTUAL research/backtest boundary
# (`ResearchDataGateService.get_research_eligible_bars`, the exact
# method `BacktestingService.for_database_backed_research`'s `run()`
# calls), not just tested against the standalone
# `migration_research_gate` helper in isolation (67.8 already covers
# that in `test_checkpoint_67_8_audit_and_research_gate.py`, unmodified
# and unaffected by this checkpoint).
#
# Requires real PostgreSQL because it persists real `MigrationRun`/
# `MigrationUnit` rows (Part 4's new, additive-only schema) into the
# disposable pytest test database and reads them back through
# `migration_research_gate_integration.resolve_migration_scope_status`
# — a genuine DB round trip, not a mock.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
    _expected_timestamps,
)
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
)
from intraday.application.services.migration_research_gate_integration import (
    MigrationStatusUndeterminable,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.migration_research_gate import MixedGridResearchRejection
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.market_data.research_bar import ProvenancedBar
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_CANONICALIZED,
    SourceTimestampSemantics,
)
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import MigrationRun, MigrationUnit
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TIMEFRAME = Timeframe.FIVE_MINUTE


class _FakeRepository:
    """Same in-memory fake as `test_research_data_gate.py` — only the
    MigrationRun/MigrationUnit audit rows below need to be real DB
    state; the underlying HistoricalBar reads stay a fixture, matching
    this file's narrow purpose (prove the migration-status WIRING, not
    re-prove 66.1's completeness/provenance gates)."""

    def __init__(self, provenanced_bars: tuple[ProvenancedBar, ...]) -> None:
        self._bars = provenanced_bars

    def get_existing_timestamps(self, instrument_id, timeframe, start, end):
        return frozenset(pb.bar.timestamp for pb in self._bars if start <= pb.bar.timestamp <= end)

    def get_bars_with_provenance(self, instrument_id, timeframe, start, end):
        return tuple(pb for pb in self._bars if start <= pb.bar.timestamp <= end)


def _full_day_bars(trading_date) -> tuple[tuple[ProvenancedBar, ...], datetime, datetime]:
    start = datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(trading_date, datetime.max.time(), tzinfo=UTC)
    expected = _expected_timestamps(start, end, TIMEFRAME, RELIANCE)
    bars = tuple(
        ProvenancedBar(
            bar=Bar(
                instrument_id=RELIANCE,
                timeframe=TIMEFRAME,
                timestamp=ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            ),
            provenance=PROVENANCE_REAL_DHAN,
            canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
            source_timestamp_semantics=SourceTimestampSemantics.OPEN.value,
        )
        for ts in expected
    )
    return bars, start, end


def _gate(bars) -> ResearchDataGateService:
    repository = _FakeRepository(bars)
    return ResearchDataGateService(
        repository=repository, coverage_service=HistoricalDataCoverageService(repository=repository)
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_boundary_allows_when_no_migration_audit_row_exists_for_scope() -> None:
    """The expected CURRENT-STATE behavior (Part 8's explicit statement
    that this gate "should currently always report no migration in
    flight"): zero `MigrationUnit` rows exist anywhere (Part 4 creates
    the schema, never populates it) - the real
    `ResearchDataGateService.get_research_eligible_bars` call must
    succeed exactly as it did before this checkpoint's wiring."""
    assert MigrationUnit.objects.count() == 0
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE)
    result = _gate(bars).get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert len(result.bars) == len(bars)


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_boundary_rejects_through_actual_gate_when_migration_running_for_scope() -> None:
    """A REAL `MigrationRun`(status=RUNNING) + `MigrationUnit` row
    covering (RELIANCE, 5m, CAS_EFFECTIVE_DATE) exists. The ACTUAL
    `get_research_eligible_bars` call - the exact method
    `BacktestingService.for_database_backed_research`'s `run()` uses -
    must raise, proving the boundary itself enforces the rule, not
    merely the standalone helper."""
    MigrationRun.objects.create(
        migration_id="mig-67-9-running",
        migration_version="2026.09-1",
        status="RUNNING",
        scope_fingerprint="a" * 64,
        started_at=datetime.now(UTC),
    )
    MigrationUnit.objects.create(
        migration_id="mig-67-9-running",
        unit_id=f"{RELIANCE}:{TIMEFRAME.value}:{CAS_EFFECTIVE_DATE.isoformat()}",
        instrument_id=str(RELIANCE),
        timeframe=TIMEFRAME.value,
        trading_date=CAS_EFFECTIVE_DATE,
        status="MIGRATING",
        old_row_count=1,
        new_row_count=1,
        old_scope_fingerprint="a" * 64,
    )

    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE)
    with pytest.raises(MixedGridResearchRejection) as exc_info:
        _gate(bars).get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason == "MIGRATION_IN_PROGRESS"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_boundary_fails_closed_denying_when_migration_status_undeterminable() -> None:
    """THE FAIL-CLOSED PROOF: a `MigrationUnit` row exists for this
    scope, but its owning `MigrationRun` row has a CORRUPT/unrecognized
    `status` string (simulating "migration status cannot be
    determined" — e.g. a future enum member this code does not yet
    know, or corrupted audit data). The safety default MUST be DENY:
    the real `get_research_eligible_bars()` call must raise
    `MigrationStatusUndeterminable`, NOT silently allow the bars
    through. This is the exact case the directive singles out: "a
    migration gate that cannot determine status MUST FAIL CLOSED. Do
    not use a feature flag that defaults to unrestricted access." """
    MigrationRun.objects.create(
        migration_id="mig-67-9-corrupt",
        migration_version="2026.09-1",
        status="__UNKNOWN_FUTURE_STATUS__",  # not a valid MigrationRunState member
        scope_fingerprint="b" * 64,
        started_at=datetime.now(UTC),
    )
    MigrationUnit.objects.create(
        migration_id="mig-67-9-corrupt",
        unit_id=f"{RELIANCE}:{TIMEFRAME.value}:{CAS_EFFECTIVE_DATE.isoformat()}",
        instrument_id=str(RELIANCE),
        timeframe=TIMEFRAME.value,
        trading_date=CAS_EFFECTIVE_DATE,
        status="MIGRATING",
        old_row_count=1,
        new_row_count=1,
        old_scope_fingerprint="b" * 64,
    )

    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE)
    with pytest.raises(MigrationStatusUndeterminable):
        _gate(bars).get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_boundary_fails_closed_when_multiple_ambiguous_unit_rows_exist() -> None:
    """A second fail-closed shape: TWO `MigrationUnit` rows both claim
    to cover the exact same (instrument_id, timeframe, trading_date) —
    an audit-data anomaly that should never happen if the Part 4
    uniqueness constraint is respected by every writer, but this proves
    the RESOLVER itself refuses to guess which one is authoritative
    rather than picking one arbitrarily and allowing research to
    proceed."""
    for i in range(2):
        MigrationRun.objects.create(
            migration_id=f"mig-67-9-dup-{i}",
            migration_version="2026.09-1",
            status="RUNNING",
            scope_fingerprint="c" * 64,
            started_at=datetime.now(UTC),
        )
        MigrationUnit.objects.create(
            migration_id=f"mig-67-9-dup-{i}",
            unit_id=f"{RELIANCE}:{TIMEFRAME.value}:{CAS_EFFECTIVE_DATE.isoformat()}",
            instrument_id=str(RELIANCE),
            timeframe=TIMEFRAME.value,
            trading_date=CAS_EFFECTIVE_DATE,
            status="MIGRATING",
            old_row_count=1,
            new_row_count=1,
            old_scope_fingerprint="c" * 64,
        )

    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE)
    with pytest.raises(MigrationStatusUndeterminable):
        _gate(bars).get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
