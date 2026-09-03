# File: .../management/commands/migration_production_execute.py
#
# Checkpoint 67.13-C — the REAL, separate production execution entry
# point `67.12.2`'s own `NOT_WIRED_RATIONALE` comment (in
# `migration_execution_authorization.py`) named as future work:
# `authorize_one_unit_execution()`'s first, and until this checkpoint
# ONLY, real caller.
#
# Structurally distinct from `migration_67_10` — a separate file, a
# separate command name, no shared `--execute` flag namespace — not a
# new mode bolted onto the existing test-only command. This is
# deliberate: `migration_67_10 --execute` exists to be invoked from
# inside pytest against the disposable test database ONLY (its own
# module docstring says so explicitly), and must keep working exactly
# as it does today, untouched by anything built here.
#
# Every one of the THREE independent gates below must pass, in order,
# before this command writes a single row:
#
#   1. `verify_environment_identity()` — must report VERIFIED_PRODUCTION.
#   2. THIS COMMAND'S OWN, EXPLICIT test-database refusal (below) — the
#      exact inverse of `assert_write_capable_connection_is_test_database`,
#      deliberately duplicated rather than only trusting the guard
#      buried inside gate 3, so a reviewer can see this command refuses
#      a test database in its own, dedicated code path.
#   3. `authorize_one_unit_execution()` — must report AUTHORIZED. This
#      independently re-checks `assert_write_capable_connection_is_test_
#      database()` too (its own check 5) — TWO independent checks
#      refusing the same wrong condition, not one hidden behind the
#      other, exactly as Checkpoint 67.13-C directed.
#
# Only past all three does this command call the SAME, UNCHANGED
# `HistoricalBarMigrationExecutor` every other execution path in this
# project already uses — no second write mechanism is invented here.
#
# CHECKPOINT 67.13-C ITSELF NEVER INVOKES THIS COMMAND AGAINST REAL
# DATA. It is built and proven here (Part 3: a test proving it refuses
# a test database) but never run for real. Using it is a separate,
# future, operator-approved checkpoint.
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError, CommandParser

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_canary_backup import build_canary_backup
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner, MigrationUnitKey
from intraday.application.services.migration_environment_identity import (
    EnvironmentIdentityVerdict,
    verify_environment_identity,
)
from intraday.application.services.migration_execute import HistoricalBarMigrationExecutor
from intraday.application.services.migration_execution_authorization import (
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationVerdict,
    authorize_one_unit_execution,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)


class ProductionEntryPointTestDatabaseRefusalError(Exception):
    """Raised by THIS command's own, explicit, dedicated test-database
    refusal (gate 2) — deliberately a distinct exception type from
    `migration_execute.py`'s `ProductionWriteGuardError`, so a reviewer
    can tell, from the exception class alone, which of the two
    independent refusal paths actually fired."""


def _parse_unit(raw: str) -> MigrationUnitKey:
    try:
        symbol, timeframe_raw, date_raw = raw.split(",")
    except ValueError as exc:
        raise CommandError(
            f"--unit must be 'SYMBOL,TIMEFRAME,YYYY-MM-DD', got: {raw!r}"
        ) from exc
    instrument_id = make_instrument_id(Exchange.NSE, symbol.strip())
    timeframe = Timeframe(timeframe_raw.strip())
    trading_date = date.fromisoformat(date_raw.strip())
    return MigrationUnitKey(instrument_id=instrument_id, timeframe=timeframe, trading_date=trading_date)


def _refuse_if_test_database() -> None:
    """Gate 2. The exact inverse of `assert_write_capable_connection_
    is_test_database` — refuses to proceed at all if the connected
    database name starts with `test_`. This command's WHOLE PURPOSE is
    to be the real-production counterpart to the test-only executor;
    a test database reaching this far would mean this command was
    invoked from the wrong context entirely."""
    from django.db import connection

    db_name = str(connection.settings_dict.get("NAME", ""))
    if db_name.startswith("test_"):
        raise ProductionEntryPointTestDatabaseRefusalError(
            f"migration_production_execute refuses to run: connection "
            f"{connection.alias!r} points at database {db_name!r}, which LOOKS "
            "LIKE a Django disposable test database (starts with 'test_'). This "
            "command exists specifically for real production execution and must "
            "NEVER run against a test database — use migration_67_10 --execute "
            "for that instead."
        )


class Command(BaseCommand):
    help = (
        "Checkpoint 67.13-C: the REAL production one-unit migration execution "
        "entry point. Requires --unit and --expected-scope-fingerprint. Refuses "
        "to write unless verify_environment_identity() reports VERIFIED_PRODUCTION, "
        "this command's own dedicated test-database refusal passes, AND "
        "authorize_one_unit_execution() reports AUTHORIZED. Three independent "
        "gates, not one. This command has never been invoked against real data "
        "as of Checkpoint 67.13-C — that decision is the operator's, separately."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--unit", required=True,
            help="'SYMBOL,TIMEFRAME,YYYY-MM-DD' — exactly one unit, this command "
            "never targets more than one.",
        )
        parser.add_argument(
            "--expected-scope-fingerprint", required=True,
            help="The operator's own, independently-recorded expected scope "
            "fingerprint for this unit — authorize_one_unit_execution()'s check "
            "(3) denies if this does not match the freshly-computed evidence.",
        )

    def handle(self, *args: object, **options: object) -> None:
        unit = _parse_unit(str(options["unit"]))
        expected_scope_fingerprint = str(options["expected_scope_fingerprint"])

        # GATE 1 — environment identity.
        self.stdout.write("Gate 1/3: verify_environment_identity()...")
        identity = verify_environment_identity()
        self.stdout.write(f"  verdict={identity.verdict.value}")
        if identity.verdict is not EnvironmentIdentityVerdict.VERIFIED_PRODUCTION:
            for reason in identity.reasons:
                self.stdout.write(self.style.ERROR(f"  reason: {reason}"))
            raise CommandError(
                "Gate 1 (environment identity) DENIED — refusing to proceed. "
                "No write attempted."
            )
        self.stdout.write(self.style.SUCCESS("  Gate 1 PASSED."))

        # GATE 2 — this command's own, explicit, dedicated test-database
        # refusal (deliberately independent of gate 3's own internal
        # re-check of the same underlying fact).
        self.stdout.write("Gate 2/3: dedicated test-database refusal...")
        _refuse_if_test_database()
        self.stdout.write(self.style.SUCCESS("  Gate 2 PASSED (not a test database)."))

        # Build the FRESH dry-run evidence this unit's authorization
        # request needs — never a stale, pre-existing artifact file;
        # always re-derived live, right here, right before authorization
        # is evaluated (the 67.12-PRE lesson: stale fingerprint tooling
        # is a real, previously-proven failure mode).
        coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
        dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
        report = dry_runner.run()
        matching = [r for r in report.units if r.unit == unit]
        if not matching:
            raise CommandError(
                f"unit {unit} was not found in a fresh dry-run plan — refusing to "
                "proceed. No write attempted."
            )
        unit_result = matching[0]
        backup_artifact = build_canary_backup(unit_result, checkpoint="67.13-C")

        # GATE 3 — authorize_one_unit_execution(), composing everything,
        # including its OWN internal re-check of the write-capability
        # guard (its check 5) — genuinely independent of gate 2 above,
        # not the same code path reused twice.
        self.stdout.write("Gate 3/3: authorize_one_unit_execution()...")
        decision = authorize_one_unit_execution(
            ExecutionAuthorizationRequest(
                environment_identity=identity,
                intended_target_unit=unit,
                backup_artifact=backup_artifact,
                expected_scope_fingerprint=expected_scope_fingerprint,
            )
        )
        if decision.verdict is not ExecutionAuthorizationVerdict.AUTHORIZED or not decision.fail_closed_ok_to_proceed():
            for reason in decision.reasons:
                self.stdout.write(self.style.ERROR(f"  reason: {reason}"))
            raise CommandError(
                "Gate 3 (authorize_one_unit_execution) DENIED — refusing to "
                "proceed. No write attempted."
            )
        self.stdout.write(self.style.SUCCESS("  Gate 3 PASSED."))

        # Only past all three gates: the SAME, UNCHANGED write mechanism
        # every other execution path in this project already uses.
        self.stdout.write(self.style.WARNING("All 3 gates passed — executing real write..."))
        executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner)
        exec_report = executor.run(unit_filter=frozenset({unit}), limit=1)
        self.stdout.write(f"run_state={exec_report.run_state.value}")
        for unit_result_out in exec_report.units:
            self.stdout.write(
                f"  unit instrument={unit_result_out.unit.instrument_id} "
                f"timeframe={unit_result_out.unit.timeframe.value} "
                f"trading_date={unit_result_out.unit.trading_date} "
                f"outcome={unit_result_out.outcome.value} "
                f"final_state={unit_result_out.final_state.value}"
            )
