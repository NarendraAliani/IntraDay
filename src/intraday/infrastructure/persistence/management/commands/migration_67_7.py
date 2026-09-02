# File: .../management/commands/migration_67_7.py
#
# Checkpoint 67.7 Part 4 — the executable DRY-RUN-ONLY migration
# runner CLI. Invoke with:
#
#     python manage.py migration_67_7 --dry-run
#
# `--dry-run` is REQUIRED, not a default-on convenience flag: omitting
# it (or any future flag meaning "commit") is refused outright, since
# no commit path exists in this checkpoint at all — there is nothing
# for a bare `migration_67_7` invocation to do. This command never
# imports `DjangoHistoricalBarRepository.bulk_upsert` or any other
# `HistoricalBar` write path; it only constructs
# `HistoricalBarMigrationDryRunner`, which is itself read-only by
# construction (see `migration_dry_run.py`'s module docstring).
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.migration_dry_run import HistoricalBarMigrationDryRunner
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)


class Command(BaseCommand):
    help = (
        "Checkpoint 67.7 dry-run-only migration runner for the HistoricalBar "
        "OPEN->CLOSE timestamp canonicalization migration. Performs zero writes; "
        "--dry-run is required."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Required. Enumerate/revalidate/simulate the migration without writing.",
        )

    def handle(self, *args: object, **options: object) -> None:
        if not options.get("dry_run"):
            raise CommandError(
                "migration_67_7 requires --dry-run; there is no write/commit mode in this "
                "checkpoint (Checkpoint 67.7 is dry-run-only by design)."
            )

        # `DjangoHistoricalBarRepository` is constructed here ONLY to
        # satisfy `HistoricalDataCoverageService`'s READ Protocol
        # (`get_existing_timestamps`) - its `bulk_upsert` write method
        # is never referenced, called, or reachable from anything this
        # command does.
        coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())
        runner = HistoricalBarMigrationDryRunner(coverage_service=coverage_service)
        report = runner.run()

        self.stdout.write(self.style.SUCCESS(f"migration_id={report.run_id}"))
        self.stdout.write(f"run_state={report.run_state.value}")
        self.stdout.write(f"eligible_row_count={report.eligible_row_count}")
        self.stdout.write(f"unit_count={report.unit_count}")
        self.stdout.write(
            f"safe_units={report.safe_unit_count} unsafe_units={report.unsafe_unit_count}"
        )
        for unit in report.units:
            self.stdout.write(
                f"  unit instrument={unit.unit.instrument_id} timeframe="
                f"{unit.unit.timeframe.value} trading_date={unit.unit.trading_date} "
                f"rows={unit.row_count} state={unit.state.value} "
                f"completeness={unit.completeness.value} proof_status={unit.proof_status} "
                f"lock_key={unit.lock_key}"
            )
            for reason in unit.unsafe_reasons:
                self.stdout.write(f"      UNSAFE: {reason}")
        self.stdout.write(self.style.SUCCESS("dry-run complete - zero HistoricalBar writes performed"))
