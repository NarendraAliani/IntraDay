# File: src/intraday/infrastructure/persistence/market_data_reference_repository.py
#
# Checkpoint 64.79: the ONE concrete `ReferenceBarRepository` this
# codebase can honestly offer today - a read-only view over the
# `HistoricalBar` table.
#
# WHY THIS TABLE IS A GENUINELY INDEPENDENT REFERENCE (the claim this
# whole checkpoint rests on, stated explicitly so it can be audited):
#
#   * different transport - Dhan's historical-candle REST endpoints
#     (`dhan/historical_client.py`), not the live market-feed
#     WebSocket;
#   * different upstream - Dhan's own consolidated exchange candles,
#     not this platform's `aggregate_quotes_into_bars()` reduction of
#     sampled quotes;
#   * different table and different write path - populated by
#     `HistoricalDataPreparationService` via
#     `DjangoHistoricalBarRepository.bulk_upsert()`, never by the live
#     worker.
#
# It is therefore NOT the "comparing two internal code paths" fallacy
# the 64.79 directive forbids. What it IS limited by is COVERAGE, and
# that limit is real: this repository can only reconcile a cell for
# which `HistoricalBar` actually holds rows at the SAME (symbol,
# timeframe, trading date). Where it does not, `reference_bars_for()`
# returns empty and the domain reports NOT_RECONCILED - which is the
# correct, non-fabricated answer.
#
# Strictly read-only: this module never writes, updates or deletes.
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from intraday.domain.market_data.archive import trading_date_for
from intraday.domain.market_data.reconciliation import ReferenceBar
from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar

DHAN_HISTORICAL_EVIDENCE_SOURCE = "dhan_historical_candle_api"
"""The `evidence_source` stamped on every report built from this
repository. Names the PIPELINE, not the table, because what makes the
comparison independent is where the numbers came from."""


class DjangoHistoricalReferenceBarRepository:
    """Satisfies `application.repositories.market_data_reconciliation.
    ReferenceBarRepository`. Structural typing only - no inheritance,
    matching this project's existing repository convention."""

    def describe_source(self) -> str:
        return DHAN_HISTORICAL_EVIDENCE_SOURCE

    def reference_bars_for(
        self,
        *,
        exchange: Exchange,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
    ) -> tuple[ReferenceBar, ...]:
        start_ist = datetime.combine(trading_date, time.min, tzinfo=INDIA_STANDARD_TIME)
        end_ist = start_ist + timedelta(days=1)
        rows = (
            HistoricalBar.objects.filter(
                exchange=exchange.value,
                symbol=instrument_symbol,
                timeframe=timeframe.value,
                bar_timestamp__gte=start_ist,
                bar_timestamp__lt=end_ist,
            )
            .order_by("bar_timestamp")
            .values_list(
                "bar_timestamp",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
            )
        )
        return tuple(
            ReferenceBar(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
            for timestamp, open_price, high_price, low_price, close_price, volume in rows
            # Defence in depth: the IST window above is already correct,
            # but re-deriving the trading date through the ONE canonical
            # rule guarantees a reference bar can never be attributed to
            # a day the archive would file it under differently.
            if trading_date_for(timestamp) == trading_date
        )


__all__ = [
    "DHAN_HISTORICAL_EVIDENCE_SOURCE",
    "DjangoHistoricalReferenceBarRepository",
]
