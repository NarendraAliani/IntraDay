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
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.models import (
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
    )
