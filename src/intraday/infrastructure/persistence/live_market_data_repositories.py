# File: src/intraday/infrastructure/persistence/live_market_data_repositories.py
#
# Checkpoint 23: Django ORM implementations of the live-market-data
# repository Protocols (application/repositories/live_market_data.py).
# Converts between the canonical domain `Quote` contract and the
# Django-specific `LiveQuoteObservation`/`MarketDataHealthStatus`
# models - the one place that conversion happens (mirrors
# `provider_settings_repositories.py`'s own encrypt/decrypt-at-the-
# boundary discipline from Checkpoint 22).
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from intraday.application.repositories.live_market_data import (
    MarketDataHealthRecord,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.archive import trading_date_for
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
    MarketDataHealthStatus,
)


class DjangoLiveQuoteRepository:
    """Django ORM implementation of `LiveQuoteRepository`."""

    def save_all(self, quotes: tuple[Quote, ...], *, fetched_at: _dt.datetime) -> None:
        rows = [
            LiveQuoteObservation(
                instrument_symbol=_symbol_from_instrument_id(quote.instrument_id),
                exchange=Exchange.NSE.value,
                last_price=quote.last_price,
                source_timestamp=quote.timestamp,
                fetched_at=fetched_at,
                # Checkpoint 64.64: persisted so a later `get_observations()`
                # round-trip (e.g. `BarAggregationService.aggregate_and_
                # persist()` reading back from the DB) still has the real
                # cumulative reading to difference into per-bar volume -
                # `None` unchanged for quotes that never carried one.
                cumulative_volume=quote.cumulative_volume,
                # Checkpoint 64.73: the trading-day identity is stamped
                # HERE, at the single write boundary, from the quote's
                # own SOURCE timestamp (never `fetched_at`, which is our
                # local receive clock - a quote observed at 15:29:59 IST
                # but written a second later must still belong to the
                # session it was quoted in).
                trading_date=trading_date_for(quote.timestamp),
                # Checkpoint 64.75: provenance, stamped at the same single
                # write boundary as `trading_date` above. `Quote.source`
                # was previously dropped here and reconstructed as `""` on
                # read - so a replayed observation could not say which
                # provider/packet path produced it. Persisted VERBATIM and
                # never defaulted to a provider name: a quote that
                # genuinely carried no source stays `""`.
                data_source=quote.source,
            )
            for quote in quotes
        ]
        LiveQuoteObservation.objects.bulk_create(rows)

    def get_latest(self) -> tuple[Quote, ...]:
        symbols = (
            LiveQuoteObservation.objects.order_by()
            .values_list("instrument_symbol", flat=True)
            .distinct()
        )
        quotes: list[Quote] = []
        for symbol in symbols:
            row = (
                LiveQuoteObservation.objects.filter(instrument_symbol=symbol)
                .order_by("-fetched_at")
                .first()
            )
            if row is not None:
                quotes.append(_row_to_quote(row))
        return tuple(quotes)

    def get_observations(self, *, since: _dt.datetime) -> tuple[Quote, ...]:
        rows = LiveQuoteObservation.objects.filter(source_timestamp__gte=since).order_by(
            "instrument_symbol", "source_timestamp"
        )
        return tuple(_row_to_quote(row) for row in rows)


class DjangoAggregatedBarRepository:
    """Django ORM implementation of `AggregatedBarRepository`. `save_all()`
    is an upsert (`update_or_create`, keyed by the unique constraint on
    `(instrument_symbol, timeframe, interval_start)`) - see the model's
    own docstring for why this differs from `LiveQuoteObservation`'s
    append-only pattern."""

    def save_all(self, bars: tuple[AggregatedBar, ...]) -> None:
        for bar in bars:
            AggregatedBarObservation.objects.update_or_create(
                instrument_symbol=_symbol_from_instrument_id(bar.instrument_id),
                timeframe=bar.timeframe.value,
                interval_start=bar.interval_start,
                defaults={
                    "exchange": Exchange.NSE.value,
                    "interval_end": bar.interval_end,
                    "open_price": bar.open,
                    "high_price": bar.high,
                    "low_price": bar.low,
                    "close_price": bar.close,
                    "status": bar.status.value,
                    "observation_count": bar.observation_count,
                    "data_source": bar.data_source,
                    "volume": bar.volume,
                    # Checkpoint 64.73: a bar belongs to the trading day
                    # it CLOSED in - derived from `interval_end`, the
                    # canonical bar timestamp.
                    "trading_date": trading_date_for(bar.interval_end),
                },
            )

    def get_recent(self, *, timeframe: Timeframe, limit: int = 200) -> tuple[AggregatedBar, ...]:
        rows = AggregatedBarObservation.objects.filter(timeframe=timeframe.value).order_by(
            "-interval_start"
        )[:limit]
        return tuple(_row_to_aggregated_bar(row) for row in rows)


class DjangoMarketDataHealthRepository:
    """Django ORM implementation of `MarketDataHealthRepository`."""

    def _singleton(self) -> MarketDataHealthStatus:
        row, _created = MarketDataHealthStatus.objects.get_or_create(pk=1)
        return row

    def get(self) -> MarketDataHealthRecord:
        row = self._singleton()
        return MarketDataHealthRecord(
            last_success_at=row.last_success_at,
            last_failure_at=row.last_failure_at,
            last_error_safe=row.last_error_safe,
            consecutive_failures=row.consecutive_failures,
        )

    def record_success(self, *, checked_at: _dt.datetime) -> None:
        row = self._singleton()
        row.last_success_at = checked_at
        row.consecutive_failures = 0
        row.save()

    def record_failure(self, *, checked_at: _dt.datetime, error_safe: str) -> None:
        row = self._singleton()
        row.last_failure_at = checked_at
        row.last_error_safe = error_safe
        row.consecutive_failures += 1
        row.save()


def _symbol_from_instrument_id(instrument_id: str) -> str:
    """`InstrumentId` is `"{exchange}:{symbol}"` (see
    `domain.instrument.contracts.make_instrument_id`) - this is the one
    place that format is parsed back apart for storage as a plain
    symbol column."""
    return str(instrument_id).split(":", maxsplit=1)[-1]


def _row_to_quote(row: LiveQuoteObservation) -> Quote:
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, row.instrument_symbol),
        timestamp=row.source_timestamp,
        last_price=Decimal(row.last_price),
        # Checkpoint 64.64: `row.cumulative_volume` round-trips back into
        # the domain `Quote` exactly as persisted - `None` stays `None`,
        # never coerced to `0` (a coerced `0` would be indistinguishable
        # from "provider genuinely reported zero volume").
        cumulative_volume=(
            Decimal(row.cumulative_volume) if row.cumulative_volume is not None else None
        ),
        # Checkpoint 64.75: provenance round-trips exactly as persisted.
        # A pre-64.75 row (no recorded provenance) yields `""` - the same
        # value `Quote.source` already defaults to - so replaying historic
        # observations is unchanged, while new ones now carry their real
        # source instead of silently losing it.
        source=row.data_source,
    )


def _row_to_aggregated_bar(row: AggregatedBarObservation) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=make_instrument_id(Exchange.NSE, row.instrument_symbol),
        timeframe=Timeframe(row.timeframe),
        interval_start=row.interval_start,
        interval_end=row.interval_end,
        open=Decimal(row.open_price),
        high=Decimal(row.high_price),
        low=Decimal(row.low_price),
        close=Decimal(row.close_price),
        status=BarStatus(row.status),
        observation_count=row.observation_count,
        data_source=row.data_source,
        # Checkpoint 64.64: real, persisted per-bar volume - see
        # `AggregatedBarObservation.volume`'s own docstring.
        volume=Decimal(row.volume),
    )
