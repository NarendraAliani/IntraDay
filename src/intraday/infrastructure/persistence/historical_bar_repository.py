# File: src/intraday/infrastructure/persistence/historical_bar_repository.py
#
# Checkpoint 63.x: Django ORM implementation of the DB-first historical
# bar archive. `DjangoHistoricalBarRepository` structurally satisfies
# THREE Protocols with one class:
#
#   - `application.repositories.historical_bars.HistoricalBarReadRepository`
#     (used by `HistoricalDataCoverageService`)
#   - `application.repositories.historical_bars.HistoricalBarWriteRepository`
#     (used by `HistoricalDataPreparationService`, the only writer)
#   - `application.repositories.HistoricalMarketDataRepository`
#     (the PRE-EXISTING, unmodified read-only Protocol
#     `HistoricalMarketDataService`/`BacktestingService` already depend
#     on) — this is the load-bearing detail that gives the scanner
#     live/backtest parity for free: once bars are persisted here,
#     `BacktestingService.run()` (Checkpoint 27, unchanged) can be
#     handed a `HistoricalMarketDataService(repository=
#     DjangoHistoricalBarRepository())` instead of the fixture
#     repository, and every downstream line of that service — strategy
#     lookup, feature computation, `run_backtest()` itself — is IDENTICAL
#     code to every other backtest in this project (Phase 10 requires
#     exactly this: "only the data source should differ").
#
# `bulk_upsert()` uses `bulk_create(..., update_conflicts=True)` keyed on
# the model's own `uq_historical_bar_identity` constraint — a single
# batched statement per fetch, not one `save()` per bar (Phase 28's
# explicit "avoid one ORM save per bar" instruction).
from __future__ import annotations

from datetime import datetime

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar


def _split_instrument_id(instrument_id: InstrumentId) -> tuple[str, str]:
    """`InstrumentId` is always `"{exchange}:{symbol}"`
    (`domain.instrument.contracts.make_instrument_id`) — this is the
    one place that splits it back apart to populate the two separate
    `exchange`/`symbol` display columns `HistoricalBar` stores
    alongside the canonical `instrument_id` string, matching the
    pattern `AggregatedBarObservation` already established."""
    exchange, _, symbol = str(instrument_id).partition(":")
    return exchange, symbol


class DjangoHistoricalBarRepository:
    def get_existing_timestamps(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> frozenset[datetime]:
        rows = HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=start,
            bar_timestamp__lte=end,
        ).values_list("bar_timestamp", flat=True)
        return frozenset(rows)

    def bulk_upsert(self, bars: tuple[Bar, ...], *, source: str) -> int:
        if not bars:
            return 0
        records = []
        for bar in bars:
            exchange, symbol = _split_instrument_id(bar.instrument_id)
            records.append(
                HistoricalBar(
                    instrument_id=str(bar.instrument_id),
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=bar.timeframe.value,
                    bar_timestamp=bar.timestamp,
                    open_price=bar.open,
                    high_price=bar.high,
                    low_price=bar.low,
                    close_price=bar.close,
                    volume=bar.volume,
                    source=source,
                )
            )
        HistoricalBar.objects.bulk_create(
            records,
            update_conflicts=True,
            unique_fields=["instrument_id", "timeframe", "bar_timestamp"],
            update_fields=[
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume",
                "source",
            ],
        )
        return len(records)

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        """Satisfies `HistoricalMarketDataRepository` (the pre-existing,
        read-only Protocol) — the scanner-facing read path. Rows are
        ordered by `bar_timestamp` at the query level so the returned
        tuple is already chronological, matching what
        `domain.market_data.quality.ensure_chronological` (called by
        `HistoricalMarketDataService.get_bars`) expects."""
        rows = HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=start,
            bar_timestamp__lte=end,
        ).order_by("bar_timestamp")
        return tuple(
            Bar(
                instrument_id=make_instrument_id(Exchange(row.exchange), row.symbol),
                timeframe=timeframe,
                timestamp=row.bar_timestamp,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=row.close_price,
                volume=row.volume,
            )
            for row in rows
        )


__all__ = ["DjangoHistoricalBarRepository"]
