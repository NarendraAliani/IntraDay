# File: .../management/commands/backfill_daily_coverage.py
#
# Checkpoint 72: OPERATOR-TRIGGERED ONLY. This command is never invoked
# automatically by anything in this codebase (no Celery Beat entry, no
# signal, no other command calls it) - the operator runs it by hand, or
# wires it to Windows Task Scheduler themselves. See
# CHECKPOINT_72_SUMMARY.md for the design rationale and setup
# instructions. Thin wrapper only - all real logic lives in the
# application-layer `daily_coverage_backfill.py` service so it stays
# testable without Django command machinery and without violating the
# "application services stay infrastructure-free" architecture rule
# (`tests/unit/architecture/test_api_boundaries.py`).
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandParser

from intraday.application.services.daily_coverage_backfill import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAME,
    most_recent_closed_trading_day,
    run_daily_backfill,
)
from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
)
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    DhanHistoricalBarProvider,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DhanInstrumentMasterProvider,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)


class Command(BaseCommand):
    help = (
        "CHECKPOINT 72: extend RELIANCE/TCS/HDFCBANK/INFY's 5m CANONICALIZED "
        "HistoricalBar coverage forward through the most recent closed trading "
        "day, using the real Dhan REST provider. Safe to run more than once a "
        "day or on a non-trading day (a fully-cached range costs zero provider "
        "calls - see CHECKPOINT_72_SUMMARY.md). Never invoked automatically by "
        "this codebase - run it manually, or schedule it yourself."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report the window that would be requested for each symbol "
                "without contacting Dhan or writing anything."
            ),
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=DEFAULT_LOOKBACK_DAYS,
            help=(
                "Calendar days back from the most recent closed trading day to "
                f"re-check each run (default {DEFAULT_LOOKBACK_DAYS})."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        as_of = datetime.now(tz=UTC)
        lookback_days = int(options["lookback_days"])

        if bool(options.get("dry_run")):
            end_date = most_recent_closed_trading_day(as_of)
            start_date = end_date - timedelta(days=lookback_days)
            self.stdout.write(
                f"DRY RUN — would request [{start_date} .. {end_date}] for "
                f"{', '.join(DEFAULT_SYMBOLS)} ({DEFAULT_TIMEFRAME.value}). "
                "No Dhan call made, nothing written."
            )
            return

        credentials = DhanSettingsService(
            repository=DjangoDhanCredentialRepository()
        ).effective_credentials()
        if credentials is None:
            self.stdout.write(
                self.style.WARNING(
                    "No Dhan credentials configured — nothing to do. This "
                    "routine deliberately never falls back to synthetic data "
                    "(that would silently contaminate real HistoricalBar rows "
                    "with fake prices)."
                )
            )
            return
        client_id, access_token = credentials

        bar_repository = DjangoHistoricalBarRepository()
        provider = DhanHistoricalBarProvider(
            client_id=client_id,
            access_token=access_token,
            instrument_master=DhanInstrumentMasterProvider(),
        )
        preparation = HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=provider,
            writer=bar_repository,
        )

        outcomes = run_daily_backfill(
            as_of=as_of, preparation=preparation, lookback_days=lookback_days
        )
        for item in outcomes:
            o = item.outcome
            self.stdout.write(
                f"{item.symbol} [{item.window_start}..{item.window_end}]: "
                f"status={o.status.value} cache_hits={o.cache_hits} "
                f"bars_fetched={o.bars_fetched} bars_persisted={o.bars_persisted} "
                f"api_requests={o.api_requests}"
                + (f" error={o.error_message!r}" if o.error_message else "")
            )
