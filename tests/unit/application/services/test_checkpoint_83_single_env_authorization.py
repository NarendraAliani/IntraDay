# File: tests/unit/application/services/test_checkpoint_83_single_env_authorization.py
#
# CHECKPOINT_83, implementing SINGLE_ENV_AUTHORIZATION_PROPOSAL.md
# §2.3(a)-(d), Part 2's own test specification:
#
#   1. HistoricalBarMigrationExecutor still refuses a non-test database
#      when allow_non_test_database=False (the default) - proves the
#      test-only path is genuinely unchanged.
#   2. It accepts a non-test database only when explicitly True AND
#      real VERIFIED_PRODUCTION identity is established.
#   3. The new row-count ceiling (MAX_ROWS_PER_EXECUTION_UNIT=200)
#      refuses an oversized unit.
#
# EVERY test in this file that touches HistoricalBar runs against
# Django's disposable pytest test database only (@requires_postgres,
# @pytest.mark.django_db(transaction=True)) - never a real connection.
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import (
    HistoricalBarMigrationDryRunner,
    MigrationUnitKey,
)
from intraday.application.services.migration_execute import (
    MAX_ROWS_PER_EXECUTION_UNIT,
    ExecuteOutcome,
    HistoricalBarMigrationExecutor,
    ProductionWriteGuardError,
    VerifiedProductionWriteGuardError,
    assert_write_capable_connection_is_verified_production,
)
from intraday.application.services.migration_environment_identity import (
    EnvironmentIdentityReport,
    EnvironmentIdentityVerdict,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")

# Same proven-scope fixture shape as test_migration_67_10_execute.py:
# 2026-08-10 is CAS-era (CAS_EFFECTIVE_DATE = 2026-08-03), NSE_EQ/5m is
# the one PROVEN scope.
_TRADING_DATE = date(2026, 8, 10)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
_FIVE_MIN = timedelta(minutes=5)


def _dense_reliance_rows(count: int) -> list[HistoricalBar]:
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


def _unit_key() -> MigrationUnitKey:
    return MigrationUnitKey(instrument_id=RELIANCE, timeframe=Timeframe.FIVE_MINUTE, trading_date=_TRADING_DATE)


def _make_dry_runner() -> HistoricalBarMigrationDryRunner:
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
    return HistoricalBarMigrationDryRunner(coverage_service=coverage_service)


def _fake_verified_production_report() -> EnvironmentIdentityReport:
    return EnvironmentIdentityReport(
        verdict=EnvironmentIdentityVerdict.VERIFIED_PRODUCTION,
        settings_module="intraday.settings.production",
        database_alias="default",
        database_name="intraday",
        database_host="localhost",
        production_marker_present=True,
        reasons=(),
    )


def _fake_cannot_verify_report() -> EnvironmentIdentityReport:
    return EnvironmentIdentityReport(
        verdict=EnvironmentIdentityVerdict.CANNOT_VERIFY,
        settings_module="intraday.settings.test",
        database_alias="default",
        database_name="test_intraday",
        database_host="localhost",
        production_marker_present=False,
        reasons=("no production marker present",),
    )


# ---------------------------------------------------------------------------
# 1. allow_non_test_database=False (the default) - unchanged behavior.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_default_executor_still_uses_the_old_test_database_guard():
    """Constructing HistoricalBarMigrationExecutor with no
    allow_non_test_database kwarg (exactly migration_67_10.py's own
    call shape) must still call assert_write_capable_connection_is_
    test_database() - proven by making THAT guard raise and confirming
    run() propagates its exact exception type, never reaching the new
    verified-production guard at all."""
    dry_runner = _make_dry_runner()
    executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner)
    assert executor.allow_non_test_database is False

    with patch(
        "intraday.application.services.migration_execute.assert_write_capable_connection_is_test_database",
        side_effect=ProductionWriteGuardError("blocked"),
    ):
        with pytest.raises(ProductionWriteGuardError):
            executor.run(unit_filter=frozenset({_unit_key()}))


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_explicit_false_still_refuses_this_real_disposable_test_connection_is_fine():
    """allow_non_test_database=False (explicit) against the real
    disposable pytest test database must NOT raise - this workspace's
    connection genuinely is test_-prefixed, the guard's designed
    acceptance case, unmodified by this checkpoint."""
    dry_runner = _make_dry_runner()
    executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner, allow_non_test_database=False)
    # Must not raise at the guard step. row_count=0 (no fixtures seeded)
    # is harmless - this test only proves the guard selection, not a
    # full successful migration.
    report = executor.run(unit_filter=frozenset({_unit_key()}))
    assert report is not None


# ---------------------------------------------------------------------------
# 2. allow_non_test_database=True - only reachable with real VERIFIED_
#    PRODUCTION identity; genuinely refuses otherwise.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_true_without_verified_production_identity_still_refuses():
    """allow_non_test_database=True does NOT itself grant write access -
    it only SELECTS the verified-production guard instead of the
    test-database guard. In this real pytest run, verify_environment_
    identity() genuinely cannot report VERIFIED_PRODUCTION (no
    production settings module, no marker), so the new guard still
    fails closed even with the flag set."""
    dry_runner = _make_dry_runner()
    executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner, allow_non_test_database=True)
    with pytest.raises(VerifiedProductionWriteGuardError):
        executor.run(unit_filter=frozenset({_unit_key()}))


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_true_with_verified_production_identity_reaches_past_the_guard():
    """With verify_environment_identity() patched (within migration_
    execute's own namespace only) to report a genuine VERIFIED_
    PRODUCTION report, allow_non_test_database=True lets run() proceed
    past the write-capability guard entirely (it never calls the old
    test-database guard at all here) - proven by seeding fixtures and
    confirming the row is actually canonicalized. Still runs against
    the disposable pytest test database underneath (@requires_postgres)
    - the guard's own identity check is what's faked, not the
    connection."""
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))
    dry_runner = _make_dry_runner()
    executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner, allow_non_test_database=True)

    with patch(
        "intraday.application.services.migration_execute.verify_environment_identity",
        side_effect=_fake_verified_production_report,
    ):
        report = executor.run(unit_filter=frozenset({_unit_key()}))

    matching = [u for u in report.units if u.unit == _unit_key()]
    assert matching
    assert matching[0].outcome is ExecuteOutcome.COMMITTED
    assert HistoricalBar.objects.filter(
        instrument_id=str(RELIANCE), canonicalization_state="CANONICALIZED"
    ).count() == 5


def test_assert_write_capable_connection_is_verified_production_denies_cannot_verify():
    """Pure unit test, no DB access: the guard function itself denies
    when verify_environment_identity() reports anything other than
    VERIFIED_PRODUCTION."""
    with patch(
        "intraday.application.services.migration_execute.verify_environment_identity",
        side_effect=_fake_cannot_verify_report,
    ):
        with pytest.raises(VerifiedProductionWriteGuardError):
            assert_write_capable_connection_is_verified_production()


def test_assert_write_capable_connection_is_verified_production_accepts_verified_production():
    """Pure unit test, no DB access: the guard does not raise when
    verify_environment_identity() genuinely reports VERIFIED_
    PRODUCTION."""
    with patch(
        "intraday.application.services.migration_execute.verify_environment_identity",
        side_effect=_fake_verified_production_report,
    ):
        assert_write_capable_connection_is_verified_production()  # must not raise


# ---------------------------------------------------------------------------
# 3. MAX_ROWS_PER_EXECUTION_UNIT=200 - refuses an oversized unit.
# ---------------------------------------------------------------------------


class _FixedReportDryRunner:
    """A minimal stand-in exposing the `.run()` shape the executor
    calls directly, returning a fixed, already-computed report,
    delegating everything else (including the real `._live_eligible_
    rows()` the executor's own revalidation pass separately calls) to
    a genuine, real `HistoricalBarMigrationDryRunner`. Used instead of
    monkeypatching `HistoricalBarMigrationDryRunner.run` directly -
    that class is a frozen, slotted dataclass, so `patch.object` on an
    instance cannot set an instance-level attribute override for it."""

    def __init__(self, report, real_dry_runner: HistoricalBarMigrationDryRunner):
        self._report = report
        self._real = real_dry_runner

    def run(self):
        return self._report

    def __getattr__(self, name):
        return getattr(self._real, name)


def _dry_run_report_with_row_count(dry_runner: HistoricalBarMigrationDryRunner, row_count: int):
    """A real NSE trading session only holds ~75 5m bars, so a genuine
    single-day unit can never itself reach MAX_ROWS_PER_EXECUTION_UNIT
    (200) rows - pushing a real fixture that high spills into
    OUT_OF_SCOPE_EXISTING_COLLISION against adjacent days, which is a
    different, unrelated refusal reason. Instead: run the REAL dry-run
    against a small, genuinely DRY_RUN_SAFE fixture, then
    `dataclasses.replace()` only its `row_count` field on the resulting
    real `UnitDryRunResult` - the ceiling check (`_execute_unit`,
    immediately after the DRY_RUN_SAFE check) reads only `.row_count`
    before returning, so every other field stays real, unmodified
    evidence from an actual dry-run pass."""
    report = dry_runner.run()
    matching = [u for u in report.units if u.unit == _unit_key()]
    assert matching, "fixture precondition: the seeded unit must appear DRY_RUN_SAFE in a real dry-run"
    assert matching[0].state.value == "DRY_RUN_SAFE"
    inflated = replace(matching[0], row_count=row_count)
    other_units = tuple(u for u in report.units if u.unit != _unit_key())
    return replace(report, units=(inflated, *other_units))


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_row_count_ceiling_refuses_a_unit_over_the_limit():
    """A DRY_RUN_SAFE unit whose row_count exceeds
    MAX_ROWS_PER_EXECUTION_UNIT is refused by _execute_unit() before
    any lock or transaction is opened (REFUSED_UNSAFE /
    REFUSED_ROW_COUNT_CEILING_EXCEEDED), and not a single row is
    canonicalized."""
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))
    dry_runner = _make_dry_runner()
    inflated_report = _dry_run_report_with_row_count(dry_runner, MAX_ROWS_PER_EXECUTION_UNIT + 1)

    executor = HistoricalBarMigrationExecutor(dry_runner=_FixedReportDryRunner(inflated_report, dry_runner))
    report = executor.run(unit_filter=frozenset({_unit_key()}))

    matching = [u for u in report.units if u.unit == _unit_key()]
    assert matching
    result = matching[0]
    assert result.outcome is ExecuteOutcome.REFUSED_UNSAFE
    assert any("REFUSED_ROW_COUNT_CEILING_EXCEEDED" in r or "exceeds" in r for r in result.reasons)
    assert HistoricalBar.objects.filter(canonicalization_state="CANONICALIZED").count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_row_count_ceiling_does_not_refuse_a_unit_at_exactly_the_limit():
    """Boundary proof: a DRY_RUN_SAFE unit with EXACTLY
    MAX_ROWS_PER_EXECUTION_UNIT rows is not refused by the ceiling
    check (row_count > MAX, not >=)."""
    HistoricalBar.objects.bulk_create(_dense_reliance_rows(5))
    dry_runner = _make_dry_runner()
    at_limit_report = _dry_run_report_with_row_count(dry_runner, MAX_ROWS_PER_EXECUTION_UNIT)

    executor = HistoricalBarMigrationExecutor(dry_runner=_FixedReportDryRunner(at_limit_report, dry_runner))
    report = executor.run(unit_filter=frozenset({_unit_key()}))

    matching = [u for u in report.units if u.unit == _unit_key()]
    assert matching
    result = matching[0]
    assert result.outcome is ExecuteOutcome.COMMITTED
    assert not any("ROW_COUNT_CEILING" in r for r in result.reasons)
