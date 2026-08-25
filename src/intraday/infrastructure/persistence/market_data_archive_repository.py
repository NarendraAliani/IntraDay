# File: src/intraday/infrastructure/persistence/market_data_archive_repository.py
#
# Checkpoint 64.73: Django ORM implementation of
# `MarketDataArchiveRepository`. Every read here is driven by the
# `trading_date` indexes added in migration 0028 - the point of this
# checkpoint is that "give me trading day X" is an indexed lookup, not
# a scan over an append-only tick log that grows by thousands of rows
# per 20 minutes of live observation.
from __future__ import annotations

import datetime as _dt
from datetime import date, datetime

from django.db.models import Count, Max, Min

from intraday.application.repositories.market_data_archive import (
    ArchiveDayRecord,
    BarCell,
    QuoteObservationSummary,
)
from intraday.domain.market_data.aggregation import AggregatedBar
from intraday.domain.market_data.archive import (
    ArchiveDayAssessment,
    ArchiveStatus,
    ReconciliationStatus,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    _row_to_aggregated_bar,
    _row_to_quote,
)
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
    MarketDataArchiveDay,
)


class DjangoMarketDataArchiveRepository:
    # --- evidence gathering ------------------------------------------
    def quote_summaries_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[QuoteObservationSummary, ...]:
        """ONE grouped aggregate query for the whole day - never a
        per-symbol loop, and never loading observation rows into
        memory just to count them."""
        rows = (
            LiveQuoteObservation.objects.filter(exchange=exchange.value, trading_date=trading_date)
            # Checkpoint 64.75: grouped by (symbol, data_source), not
            # symbol alone - still ONE aggregate query for the whole day.
            .values("instrument_symbol", "data_source")
            .annotate(
                observation_count=Count("id"),
                first_observation_at=Min("source_timestamp"),
                last_observation_at=Max("source_timestamp"),
            )
            .order_by("instrument_symbol", "data_source")
        )
        return tuple(
            QuoteObservationSummary(
                instrument_symbol=row["instrument_symbol"],
                observation_count=row["observation_count"],
                first_observation_at=row["first_observation_at"],
                last_observation_at=row["last_observation_at"],
                data_source=row["data_source"],
            )
            for row in rows
        )

    def bar_cells_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[BarCell, ...]:
        rows = AggregatedBarObservation.objects.filter(
            exchange=exchange.value, trading_date=trading_date
        ).order_by("instrument_symbol", "timeframe", "interval_start")

        grouped: dict[tuple[str, str, str], list[AggregatedBarObservation]] = {}
        for row in rows:
            grouped.setdefault((row.instrument_symbol, row.timeframe, row.data_source), []).append(
                row
            )

        cells: list[BarCell] = []
        for (symbol, timeframe_value, data_source), bar_rows in grouped.items():
            try:
                timeframe = Timeframe(timeframe_value)
            except ValueError:
                # An unrecognised timeframe string is reported by being
                # SKIPPED loudly-in-data rather than crashing the whole
                # day's refresh - it cannot be assessed against a
                # session it has no duration for.
                continue
            closed = tuple(row.interval_end for row in bar_rows if row.status == "CLOSED")
            forming = sum(1 for row in bar_rows if row.status == "FORMING")
            cells.append(
                BarCell(
                    instrument_symbol=symbol,
                    timeframe=timeframe,
                    data_source=data_source,
                    closed_bar_close_timestamps=closed,
                    forming_bar_count=forming,
                )
            )
        return tuple(cells)

    # --- assessment persistence --------------------------------------
    def save_assessment(self, assessment: ArchiveDayAssessment, *, computed_at: datetime) -> None:
        MarketDataArchiveDay.objects.update_or_create(
            exchange=assessment.identity.exchange.value,
            trading_date=assessment.identity.trading_date,
            instrument_symbol=assessment.instrument_symbol,
            timeframe=assessment.timeframe.value,
            data_source=assessment.data_source,
            defaults={
                "status": assessment.status.value,
                "reason": assessment.reason,
                "completeness_supported": assessment.completeness_supported,
                "expected_bar_count": assessment.expected_bar_count,
                "closed_bar_count": assessment.closed_bar_count,
                "forming_bar_count": assessment.forming_bar_count,
                "missing_bar_count": assessment.missing_bar_count,
                "duplicate_bar_count": len(assessment.duplicate_bar_timestamps),
                "quote_observation_count": assessment.quote_observation_count,
                "first_observation_at": assessment.first_observation_at,
                "last_observation_at": assessment.last_observation_at,
                # Never overwritten by a refresh: reconciliation is an
                # INDEPENDENT verdict, and recomputing the archive from
                # our own observations must never be able to promote a
                # day to "reconciled".
                "computed_at": computed_at,
            },
        )

    # --- queryability -------------------------------------------------
    def list_archive_days(
        self,
        *,
        trading_date: date,
        exchange: Exchange | None = None,
        instrument_symbol: str | None = None,
        timeframe: Timeframe | None = None,
    ) -> tuple[ArchiveDayRecord, ...]:
        queryset = MarketDataArchiveDay.objects.filter(trading_date=trading_date)
        if exchange is not None:
            queryset = queryset.filter(exchange=exchange.value)
        if instrument_symbol is not None:
            queryset = queryset.filter(instrument_symbol=instrument_symbol)
        if timeframe is not None:
            queryset = queryset.filter(timeframe=timeframe.value)
        return tuple(
            _row_to_archive_day(row)
            for row in queryset.order_by("instrument_symbol", "timeframe", "data_source")
        )

    def list_bars(
        self,
        *,
        exchange: Exchange,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
    ) -> tuple[AggregatedBar, ...]:
        rows = AggregatedBarObservation.objects.filter(
            exchange=exchange.value,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe.value,
        ).order_by("interval_start")
        return tuple(_row_to_aggregated_bar(row) for row in rows)

    def list_quote_observations(
        self, *, exchange: Exchange, trading_date: date, instrument_symbol: str
    ) -> tuple[Quote, ...]:
        rows = LiveQuoteObservation.objects.filter(
            exchange=exchange.value,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
        ).order_by("source_timestamp")
        return tuple(_row_to_quote(row) for row in rows)

    def archived_symbols_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[str, ...]:
        """Every symbol with ANY observed data on the day - the union of
        the raw-quote and bar layers, so a symbol whose quotes arrived
        but never formed a closed bar is still reported as archived
        rather than silently vanishing."""
        quote_symbols = set(
            LiveQuoteObservation.objects.filter(exchange=exchange.value, trading_date=trading_date)
            .order_by()
            .values_list("instrument_symbol", flat=True)
            .distinct()
        )
        bar_symbols = set(
            AggregatedBarObservation.objects.filter(
                exchange=exchange.value, trading_date=trading_date
            )
            .order_by()
            .values_list("instrument_symbol", flat=True)
            .distinct()
        )
        return tuple(sorted(quote_symbols | bar_symbols))


def _row_to_archive_day(row: MarketDataArchiveDay) -> ArchiveDayRecord:
    return ArchiveDayRecord(
        exchange=Exchange(row.exchange),
        trading_date=row.trading_date,
        instrument_symbol=row.instrument_symbol,
        timeframe=Timeframe(row.timeframe),
        data_source=row.data_source,
        status=ArchiveStatus(row.status),
        reason=row.reason,
        completeness_supported=row.completeness_supported,
        expected_bar_count=row.expected_bar_count,
        closed_bar_count=row.closed_bar_count,
        forming_bar_count=row.forming_bar_count,
        missing_bar_count=row.missing_bar_count,
        duplicate_bar_count=row.duplicate_bar_count,
        quote_observation_count=row.quote_observation_count,
        first_observation_at=_as_utc(row.first_observation_at),
        last_observation_at=_as_utc(row.last_observation_at),
        reconciliation_status=ReconciliationStatus(row.reconciliation_status),
        reconciled_at=_as_utc(row.reconciled_at),
        computed_at=_as_utc(row.computed_at),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.UTC)
    return value.astimezone(_dt.UTC)


__all__ = ["DjangoMarketDataArchiveRepository"]
