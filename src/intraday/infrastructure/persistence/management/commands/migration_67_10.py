# File: .../management/commands/migration_67_10.py
#
# Checkpoint 67.10 — the EXECUTABLE (write-capable) sibling of
# `migration_67_7`. Two modes, mutually exclusive, exactly one
# required per invocation:
#
#     python manage.py migration_67_10 --dry-run
#         Byte-for-byte identical behavior to `migration_67_7
#         --dry-run` (constructs the SAME `HistoricalBarMigrationDryRunner`,
#         zero writes) - kept here only so a single command can serve
#         as the durable entry point going forward; `migration_67_7`
#         itself is UNCHANGED and still works exactly as before.
#
#     python manage.py migration_67_10 --execute [--unit INSTRUMENT,TIMEFRAME,YYYY-MM-DD]
#                                                 [--limit N]
#         Write-capable. Targets a SPECIFIC SUBSET of units (never
#         "all 147 or nothing" - Checkpoint 67.12 will eventually need
#         to target exactly one unit). Refuses to run at all unless the
#         active DB connection looks like a Django disposable test
#         database (`assert_write_capable_connection_is_test_database`)
#         - this is a HARD, code-level guard, not just operator
#         discipline, and it is why this command must NEVER be invoked
#         with `--execute` against the dev/production settings module
#         in this checkpoint.
#
# `--unit` may be repeated to target several specific units in one
# invocation; omitting both `--unit` and `--limit` with `--execute`
# targets every currently DRY_RUN_SAFE unit (still gated by the
# test-database guard) - this checkpoint's own tests always pass
# `--unit`/`--limit` explicitly and only ever call this from inside a
# pytest test function scoped to the disposable test DB, never from a
# real shell invocation.
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError, CommandParser

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner, MigrationUnitKey
from intraday.application.services.migration_execute import HistoricalBarMigrationExecutor
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)


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


class Command(BaseCommand):
    help = (
        "Checkpoint 67.10 executable migration runner. Exactly one of --dry-run "
        "(read-only, identical to migration_67_7) or --execute (write-capable, "
        "test-database-only) is required."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument("--execute", action="store_true", default=False)
        parser.add_argument(
            "--unit", action="append", default=None,
            help="'SYMBOL,TIMEFRAME,YYYY-MM-DD' - may be repeated. Only valid with --execute.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Cap the number of units --execute touches. Only valid with --execute.",
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options.get("dry_run"))
        execute = bool(options.get("execute"))

        if dry_run and execute:
            raise CommandError("migration_67_10 accepts exactly one of --dry-run or --execute, not both")
        if not dry_run and not execute:
            raise CommandError("migration_67_10 requires exactly one of --dry-run or --execute")

        coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
        dry_runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)

        if dry_run:
            report = dry_runner.run()
            self.stdout.write(self.style.SUCCESS(f"migration_id={report.run_id}"))
            self.stdout.write(f"run_state={report.run_state.value}")
            self.stdout.write(f"eligible_row_count={report.eligible_row_count}")
            self.stdout.write(f"unit_count={report.unit_count}")
            self.stdout.write(
                f"safe_units={report.safe_unit_count} unsafe_units={report.unsafe_unit_count}"
            )
            self.stdout.write(self.style.SUCCESS("dry-run complete - zero HistoricalBar writes performed"))
            return

        raw_units = options.get("unit")
        unit_filter = frozenset(_parse_unit(u) for u in raw_units) if raw_units else None
        limit = options.get("limit")

        executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner)
        report = executor.run(unit_filter=unit_filter, limit=limit)

        self.stdout.write(self.style.WARNING(f"migration_id={report.run_id} EXECUTE MODE"))
        self.stdout.write(f"run_state={report.run_state.value}")
        self.stdout.write(f"requested_unit_count={report.requested_unit_count}")
        self.stdout.write(
            f"committed={report.committed_unit_count} stopped={report.stopped_unit_count} "
            f"refused={report.refused_unit_count} failed={report.failed_unit_count}"
        )
        for unit_result in report.units:
            self.stdout.write(
                f"  unit instrument={unit_result.unit.instrument_id} "
                f"timeframe={unit_result.unit.timeframe.value} "
                f"trading_date={unit_result.unit.trading_date} "
                f"outcome={unit_result.outcome.value} final_state={unit_result.final_state.value}"
            )
