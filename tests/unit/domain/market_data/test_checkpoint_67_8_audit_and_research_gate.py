# File: tests/unit/domain/market_data/test_checkpoint_67_8_audit_and_research_gate.py
#
# Checkpoint 67.8 Parts 9-10 — contract tests for the design-only
# persistent audit dataclasses (no DB, no migration) and the mixed-grid
# research-gate rule (pure predicate, no DB).
from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.migration_audit import (
    MigrationRunAuditRecord,
    MigrationUnitAuditRecord,
    assert_unique_migration_run_ids,
    assert_unique_migration_unit_pairs,
)
from intraday.domain.market_data.migration_research_gate import (
    MigrationScopeStatus,
    MixedGridResearchRejection,
    migration_scope_is_research_eligible,
    require_migration_scope_research_eligible,
)
from intraday.domain.market_data.migration_state import MigrationRunState, MigrationUnitState
from intraday.domain.market_data.source_timestamp import CANONICALIZATION_STATE_CANONICALIZED
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
DAY = date(2026, 1, 5)


def test_run_audit_record_uniqueness_rejects_duplicate_migration_id() -> None:
    a = MigrationRunAuditRecord(
        migration_id="67.8-X",
        status=MigrationRunState.PLANNED,
        started_at=datetime.now(dt_timezone.utc),
        completed_at=None,
        migration_version="1",
        scope="test",
    )
    b = MigrationRunAuditRecord(
        migration_id="67.8-X",
        status=MigrationRunState.RUNNING,
        started_at=datetime.now(dt_timezone.utc),
        completed_at=None,
        migration_version="1",
        scope="test",
    )
    with pytest.raises(ValueError):
        assert_unique_migration_run_ids((a, b))


def test_unit_audit_record_uniqueness_is_migration_id_and_unit_id() -> None:
    a = MigrationUnitAuditRecord(
        migration_id="67.8-X",
        unit_id="RELIANCE:5m:2026-01-05",
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        status=MigrationUnitState.PENDING,
        old_row_count=75,
        new_row_count=75,
        error_code=None,
        committed_at=None,
    )
    b = MigrationUnitAuditRecord(
        migration_id="67.8-X",
        unit_id="RELIANCE:5m:2026-01-05",
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        status=MigrationUnitState.COMMITTED,
        old_row_count=75,
        new_row_count=75,
        error_code=None,
        committed_at=datetime.now(dt_timezone.utc),
    )
    with pytest.raises(ValueError):
        assert_unique_migration_unit_pairs((a, b))

    # a DIFFERENT unit_id under the same migration_id is fine.
    c = MigrationUnitAuditRecord(
        migration_id="67.8-X",
        unit_id="RELIANCE:5m:2026-01-06",
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=date(2026, 1, 6),
        status=MigrationUnitState.PENDING,
        old_row_count=75,
        new_row_count=75,
        error_code=None,
        committed_at=None,
    )
    assert_unique_migration_unit_pairs((a, c))  # does not raise


def test_no_migration_touching_scope_imposes_no_restriction() -> None:
    assert migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=None,
        unit_is_complete=True,
    )


@pytest.mark.parametrize("run_state", [MigrationRunState.RUNNING, MigrationRunState.PARTIALLY_COMPLETED])
def test_running_or_partially_completed_rejects_unconditionally(
    run_state: MigrationRunState,
) -> None:
    status = MigrationScopeStatus(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        run_state=run_state,
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,  # even if canonical+complete
    )
    assert not migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=status,
        unit_is_complete=True,
    )
    with pytest.raises(MixedGridResearchRejection) as exc_info:
        require_migration_scope_research_eligible(
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            trading_date=DAY,
            scope_status=status,
            unit_is_complete=True,
        )
    assert exc_info.value.reason == "MIGRATION_IN_PROGRESS"


def test_completed_run_requires_both_canonicalized_and_complete() -> None:
    canonical_and_complete = MigrationScopeStatus(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        run_state=MigrationRunState.COMPLETED,
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
    )
    assert migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=canonical_and_complete,
        unit_is_complete=True,
    )
    # COMPLETED run but this unit not canonicalized -> reject.
    not_canonical = MigrationScopeStatus(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        run_state=MigrationRunState.COMPLETED,
        canonicalization_state="UNCANONICALIZED",
    )
    assert not migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=not_canonical,
        unit_is_complete=True,
    )
    # COMPLETED run, canonicalized, but incomplete -> reject.
    assert not migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=canonical_and_complete,
        unit_is_complete=False,
    )


@pytest.mark.parametrize("run_state", [MigrationRunState.PLANNED, MigrationRunState.ABORTED])
def test_planned_or_aborted_imposes_no_restriction(run_state: MigrationRunState) -> None:
    status = MigrationScopeStatus(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        run_state=run_state,
        canonicalization_state="UNCANONICALIZED",
    )
    assert migration_scope_is_research_eligible(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        scope_status=status,
        unit_is_complete=False,
    )


def test_mismatched_scope_status_fails_closed_with_value_error() -> None:
    wrong_unit_status = MigrationScopeStatus(
        instrument_id=make_instrument_id(Exchange.NSE, "INFY"),
        timeframe=Timeframe.FIVE_MINUTE,
        trading_date=DAY,
        run_state=MigrationRunState.RUNNING,
        canonicalization_state="UNCANONICALIZED",
    )
    with pytest.raises(ValueError):
        migration_scope_is_research_eligible(
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            trading_date=DAY,
            scope_status=wrong_unit_status,
            unit_is_complete=True,
        )
