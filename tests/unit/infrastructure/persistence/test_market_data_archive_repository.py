# tests/unit/infrastructure/persistence/test_market_data_archive_repository.py
#
# Checkpoint 64.73: real-database coverage for the daily market-data
# archive - trading-date stamping at the write boundary, whole-day and
# per-symbol/timeframe queryability, idempotent assessment upsert, and
# the archive status a genuinely partial live session must produce.
#
# No provider connection, no strategy, no order path is exercised here.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.archive import ArchiveStatus
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
)
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
    MarketDataArchiveDay,
)
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TRADING_DAY = date(2026, 8, 25)
MARKET_OPEN = datetime(2026, 8, 25, 3, 45, tzinfo=UTC)  # 09:15 IST
AFTER_CLOSE = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)  # 17:30 IST
# 00:30 IST on the 25th - the UTC calendar date here is the 24th, so a
# naive `.date()` would file this under the WRONG trading day.
PRE_DAWN = datetime(2026, 8, 24, 19, 0, tzinfo=UTC)


def _quote(timestamp: datetime, price: str = "100.00") -> Quote:
    return Quote(
        instrument_id=RELIANCE,
        last_price=Decimal(price),
        timestamp=timestamp,
        cumulative_volume=Decimal("1000"),
    )


def _bar(interval_start: datetime, status: BarStatus = BarStatus.CLOSED) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(minutes=1),
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("98.00"),
        close=Decimal("101.00"),
        status=status,
        observation_count=3,
        data_source="dhan",
    )


@requires_postgres
@pytest.mark.django_db
def test_quote_write_stamps_ist_trading_date_not_utc_date() -> None:
    DjangoLiveQuoteRepository().save_all((_quote(PRE_DAWN),), fetched_at=AFTER_CLOSE)

    row = LiveQuoteObservation.objects.get()
    assert row.source_timestamp.date() == date(2026, 8, 24)
    assert row.trading_date == TRADING_DAY


@requires_postgres
@pytest.mark.django_db
def test_bar_write_stamps_trading_date_from_close_instant() -> None:
    DjangoAggregatedBarRepository().save_all((_bar(MARKET_OPEN),))

    assert AggregatedBarObservation.objects.get().trading_date == TRADING_DAY


@requires_postgres
@pytest.mark.django_db
def test_whole_day_and_per_symbol_queries_return_only_that_day() -> None:
    repo = DjangoMarketDataArchiveRepository()
    DjangoLiveQuoteRepository().save_all(
        (_quote(MARKET_OPEN), _quote(MARKET_OPEN + timedelta(days=1))),
        fetched_at=AFTER_CLOSE,
    )
    DjangoAggregatedBarRepository().save_all(
        (_bar(MARKET_OPEN), _bar(MARKET_OPEN + timedelta(days=1)))
    )

    assert repo.archived_symbols_for_trading_date(
        exchange=Exchange.NSE, trading_date=TRADING_DAY
    ) == ("RELIANCE",)
    assert (
        len(
            repo.list_quote_observations(
                exchange=Exchange.NSE, trading_date=TRADING_DAY, instrument_symbol="RELIANCE"
            )
        )
        == 1
    )
    assert (
        len(
            repo.list_bars(
                exchange=Exchange.NSE,
                trading_date=TRADING_DAY,
                instrument_symbol="RELIANCE",
                timeframe=Timeframe.ONE_MINUTE,
            )
        )
        == 1
    )


@requires_postgres
@pytest.mark.django_db
def test_quote_summary_aggregates_first_and_last_observation() -> None:
    later = MARKET_OPEN + timedelta(minutes=30)
    DjangoLiveQuoteRepository().save_all(
        (_quote(MARKET_OPEN), _quote(later)), fetched_at=AFTER_CLOSE
    )

    (summary,) = DjangoMarketDataArchiveRepository().quote_summaries_for_trading_date(
        exchange=Exchange.NSE, trading_date=TRADING_DAY
    )
    assert summary.observation_count == 2
    assert summary.first_observation_at == MARKET_OPEN
    assert summary.last_observation_at == later


@requires_postgres
@pytest.mark.django_db
def test_partial_session_is_archived_as_partial_not_complete() -> None:
    """The 64.72 shape, end to end through the real database: a short
    observation window produces real rows and an honest PARTIAL."""
    DjangoLiveQuoteRepository().save_all((_quote(MARKET_OPEN),), fetched_at=AFTER_CLOSE)
    DjangoAggregatedBarRepository().save_all(
        tuple(_bar(MARKET_OPEN + timedelta(minutes=i)) for i in range(20))
    )
    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

    (assessment,) = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    # Checkpoint 64.88: RELIANCE is a CATEGORY_I_CAS symbol, so the
    # correct continuous-trading expectation is 09:15-15:15 IST (360
    # one-minute bars), not the old uniform 09:15-15:30 (375) - the
    # exact fix this checkpoint makes. See `CATEGORY_I_CAS_SYMBOLS`.
    assert assessment.status is ArchiveStatus.PARTIAL
    assert assessment.closed_bar_count == 20
    assert assessment.expected_bar_count == 360
    assert assessment.missing_bar_count == 340

    summary = service.describe_trading_date(trading_date=TRADING_DAY)
    assert summary.status is ArchiveStatus.PARTIAL
    assert summary.symbol_count == 1


@requires_postgres
@pytest.mark.django_db
def test_refresh_is_idempotent() -> None:
    DjangoAggregatedBarRepository().save_all((_bar(MARKET_OPEN),))
    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

    service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)
    service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)
    service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    assert MarketDataArchiveDay.objects.count() == 1
    assert MarketDataArchiveDay.objects.get().reconciliation_status == "NOT_RECONCILED"


@requires_postgres
@pytest.mark.django_db
def test_forming_bars_are_counted_separately_from_closed() -> None:
    DjangoAggregatedBarRepository().save_all(
        (
            _bar(MARKET_OPEN),
            _bar(MARKET_OPEN + timedelta(minutes=1), status=BarStatus.FORMING),
        )
    )
    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

    (assessment,) = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    assert assessment.closed_bar_count == 1
    assert assessment.forming_bar_count == 1


@requires_postgres
@pytest.mark.django_db
def test_untouched_trading_day_reports_not_observed() -> None:
    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

    summary = service.describe_trading_date(trading_date=TRADING_DAY)

    assert summary.status is ArchiveStatus.NOT_OBSERVED
    assert summary.cells == ()
