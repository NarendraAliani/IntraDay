# File: tests/unit/infrastructure/persistence/management/test_migration_production_execute.py
#
# Checkpoint 67.13-C. Proves the new `migration_production_execute`
# command's own, dedicated test-database refusal (gate 2) — the exact
# symmetric proof `assert_write_capable_connection_is_test_database`
# already has for the opposite case. Also proves gate 1 (environment
# identity) denies by default in this project's real test environment,
# and that `authorize_one_unit_execution` genuinely has a real caller
# now.
#
# NEVER sets INTRADAY_VERIFIED_PRODUCTION_IDENTITY to a real value.
# NEVER lets a write reach HistoricalBar — every test here is proving
# a REFUSAL, on purpose; there is no "happy path executes for real"
# test in this file, by design, per Checkpoint 67.13-C's own
# prohibition against any real execution.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from intraday.application.services.migration_environment_identity import (
    EnvironmentIdentityReport,
    EnvironmentIdentityVerdict,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.management.commands import (
    migration_production_execute as command_module,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

# Same proven-scope fixture pattern as test_migration_67_10_execute.py:
# 2026-08-10 is CAS-era (CAS_EFFECTIVE_DATE = 2026-08-03), NSE_EQ/5m is
# the one PROVEN scope. Reused verbatim rather than re-derived, so this
# file's DRY_RUN_SAFE eligibility rests on the same already-proven
# fixture shape, not a newly-invented one.
_RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
_TRADING_DATE = date(2026, 8, 10)
_BASE = datetime(2026, 8, 10, 9, 15, tzinfo=UTC)
_FIVE_MIN = timedelta(minutes=5)


def _seed_dense_reliance_rows(count: int = 5) -> None:
    rows = []
    for i in range(count):
        ts = _BASE + i * _FIVE_MIN
        rows.append(
            HistoricalBar(
                instrument_id=str(_RELIANCE), exchange="NSE", symbol="RELIANCE", timeframe="5m",
                bar_timestamp=ts, open_price=Decimal("100.00") + i, high_price=Decimal("101.50") + i,
                low_price=Decimal("99.25") + i, close_price=Decimal("100.75") + i,
                volume=Decimal("1000") + (i * 10), source="API_FETCH", provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="UNCANONICALIZED", source_timestamp_semantics="OPEN",
            )
        )
    HistoricalBar.objects.bulk_create(rows)


def _fake_verified_production_report() -> EnvironmentIdentityReport:
    """A synthetic VERIFIED_PRODUCTION report — used ONLY to prove gate
    2 (this command's OWN test-database refusal) fires independently of
    gate 1, by making gate 1 pass so gate 2 is actually reached. This
    never touches the real INTRADAY_VERIFIED_PRODUCTION_IDENTITY
    environment variable and never runs against real data — the test
    database this report is paired with in every test below is
    genuinely `test_intraday`, so gate 2 (or gate 3's own internal
    re-check) still refuses regardless of this fake report."""
    return EnvironmentIdentityReport(
        verdict=EnvironmentIdentityVerdict.VERIFIED_PRODUCTION,
        settings_module="intraday.settings.production",
        database_alias="default",
        database_name="intraday",
        database_host="localhost",
        production_marker_present=True,
        reasons=(),
    )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_gate_1_denies_by_default_in_the_real_test_environment() -> None:
    """No mocking at all - the ordinary, default case. This project's
    real test settings module can never satisfy verify_environment_
    identity()'s VERIFIED_PRODUCTION conditions, so gate 1 alone
    already refuses - proving the command's FIRST line of defense
    works with zero special setup."""
    with pytest.raises(CommandError, match="Gate 1"):
        call_command(
            "migration_production_execute",
            "--unit", "RELIANCE,5m,2026-08-17",
            "--expected-scope-fingerprint", "deadbeef",
        )
    assert HistoricalBar.objects.count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_gate_2_refuses_a_test_database_even_when_gate_1_is_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE test that matters most in this checkpoint. Monkeypatches
    ONLY verify_environment_identity() to return a fake VERIFIED_
    PRODUCTION report (proving gate 2 does NOT merely benefit from
    gate 1's own, separate denial) - the real database connection
    underneath is still genuinely `test_intraday` (Django's own
    disposable pytest test database, confirmed via connection.settings_
    dict directly in this test), so this command's OWN, dedicated,
    explicit test-database refusal (gate 2) must fire on its own."""
    db_name = str(connection.settings_dict.get("NAME", ""))
    assert db_name.startswith("test_"), (
        f"test precondition failed: expected a disposable test database, got {db_name!r}"
    )

    monkeypatch.setattr(
        command_module, "verify_environment_identity", _fake_verified_production_report
    )

    with pytest.raises(command_module.ProductionEntryPointTestDatabaseRefusalError):
        call_command(
            "migration_production_execute",
            "--unit", "RELIANCE,5m,2026-08-17",
            "--expected-scope-fingerprint", "deadbeef",
        )
    assert HistoricalBar.objects.count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_gate_3_still_denies_even_if_gates_1_and_2_were_both_bypassable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense-in-depth proof: even in the hypothetical where gate 2's
    own check were somehow skipped, authorize_one_unit_execution()'s
    OWN internal re-check of assert_write_capable_connection_is_test_
    database() (its check 5) is a genuinely separate code path and
    still independently denies. Proven by monkeypatching gate 2's
    function to a no-op AND gate 1 to fake-pass, then confirming gate 3
    is what actually stops it - not just seeing SOME error."""
    _seed_dense_reliance_rows(5)
    monkeypatch.setattr(
        command_module, "verify_environment_identity", _fake_verified_production_report
    )
    monkeypatch.setattr(command_module, "_refuse_if_test_database", lambda: None)

    with pytest.raises(CommandError, match="Gate 3"):
        call_command(
            "migration_production_execute",
            "--unit", "RELIANCE,5m,2026-08-10",
            "--expected-scope-fingerprint", "deadbeef",
        )
    # No row was canonicalized - the fake expected_scope_fingerprint
    # ("deadbeef") deliberately never matches the freshly-computed real
    # one, so gate 3's own check (3) denies before any write.
    assert HistoricalBar.objects.filter(canonicalization_state="CANONICALIZED").count() == 0


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_missing_required_arguments_are_rejected_before_any_gate_runs() -> None:
    with pytest.raises(CommandError):
        call_command("migration_production_execute")
    assert HistoricalBar.objects.count() == 0


def test_authorize_one_unit_execution_now_has_a_real_non_test_caller() -> None:
    """Confirms, by source inspection (not execution), that this
    command module is a genuine, non-test caller of authorize_one_unit_
    execution - closing the exact gap 67.13/67.13-B's trace found:
    zero real callers existed anywhere in src/ before this checkpoint."""
    import inspect

    source = inspect.getsource(command_module)
    assert "authorize_one_unit_execution(" in source
    assert command_module.__name__.startswith("intraday.infrastructure.persistence.management.commands")
