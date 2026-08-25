# File: .../management/commands/market_data_archive.py
#
# Checkpoint 64.73: the operator/research entry point to the daily
# market-data archive. Read-and-classify only - this command NEVER
# deletes market data, never places an order, never runs a strategy,
# and never connects to a provider. It reads what was already
# persisted, asks the domain to classify it, and upserts the resulting
# archive-day rows.
from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand, CommandParser

from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.domain.market_data.archive import trading_date_for
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)


class Command(BaseCommand):
    help = (
        "Refresh and/or report the daily market-data archive status for a trading date. "
        "Never deletes data and never contacts a market-data provider."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--date",
            default=None,
            help="Trading date as YYYY-MM-DD (IST). Defaults to today's IST trading date.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Recompute archive status from the underlying observations before reporting.",
        )
        parser.add_argument("--symbol", default=None, help="Restrict the report to one symbol.")

    def handle(self, *args: object, **options: object) -> None:
        now = dt.datetime.now(tz=dt.UTC)
        raw_date = options.get("date")
        trading_date = dt.date.fromisoformat(str(raw_date)) if raw_date else trading_date_for(now)

        service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

        if bool(options.get("refresh")):
            assessments = service.refresh_trading_date(trading_date=trading_date, as_of=now)
            self.stdout.write(f"refreshed {len(assessments)} archive cell(s) for {trading_date}")

        summary = service.describe_trading_date(trading_date=trading_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"{summary.identity.key} status={summary.status.value} "
                f"trading_day={summary.is_trading_day} symbols={summary.symbol_count}"
            )
        )
        symbol_filter = options.get("symbol")
        for cell in summary.cells:
            if symbol_filter and cell.instrument_symbol != str(symbol_filter):
                continue
            self.stdout.write(
                f"  {cell.instrument_symbol} {cell.timeframe.value} "
                f"source={cell.data_source} status={cell.status.value} "
                f"reason={cell.reason} closed={cell.closed_bar_count}/"
                f"{cell.expected_bar_count} missing={cell.missing_bar_count} "
                f"quotes={cell.quote_observation_count} "
                f"reconciliation={cell.reconciliation_status.value}"
            )
        if not summary.cells:
            self.stdout.write("  (no archive cells - run with --refresh, or no data was observed)")
