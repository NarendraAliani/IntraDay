# tests/unit/infrastructure/persistence/test_aggregated_bar_repository.py
#
# Checkpoint 24A: Django ORM repository coverage - upsert-by-identity
# behavior, real persistence, real retrieval.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
)
from intraday.infrastructure.persistence.models import AggregatedBarObservation
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)


def _bar(
    interval_start: datetime = BASE,
    status: BarStatus = BarStatus.CLOSED,
    close: str = "100.00",
) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(minutes=1),
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("98.00"),
        close=Decimal(close),
        status=status,
        observation_count=3,
        data_source="dhan",
    )


@requires_postgres
@pytest.mark.django_db
def test_get_recent_before_any_save_returns_empty() -> None:
    repo = DjangoAggregatedBarRepository()

    assert repo.get_recent(timeframe=Timeframe.ONE_MINUTE) == ()


@requires_postgres
@pytest.mark.django_db
def test_save_then_get_recent_round_trips() -> None:
    repo = DjangoAggregatedBarRepository()

    repo.save_all((_bar(),))

    bars = repo.get_recent(timeframe=Timeframe.ONE_MINUTE)
    assert len(bars) == 1
    assert bars[0].close == Decimal("100.00")
    assert bars[0].status is BarStatus.CLOSED


@requires_postgres
@pytest.mark.django_db
def test_save_all_upserts_by_instrument_timeframe_interval_start() -> None:
    """A FORMING bar becoming CLOSED (or any revision) must update the
    existing row in place, never create a duplicate."""
    repo = DjangoAggregatedBarRepository()
    repo.save_all((_bar(status=BarStatus.FORMING, close="100.00"),))
    repo.save_all((_bar(status=BarStatus.CLOSED, close="103.00"),))

    assert AggregatedBarObservation.objects.count() == 1
    bars = repo.get_recent(timeframe=Timeframe.ONE_MINUTE)
    assert bars[0].status is BarStatus.CLOSED
    assert bars[0].close == Decimal("103.00")


@requires_postgres
@pytest.mark.django_db
def test_get_recent_returns_newest_first() -> None:
    repo = DjangoAggregatedBarRepository()
    earlier = BASE
    later = BASE + timedelta(minutes=5)
    repo.save_all((_bar(interval_start=earlier), _bar(interval_start=later)))

    bars = repo.get_recent(timeframe=Timeframe.ONE_MINUTE)

    assert bars[0].interval_start == later
    assert bars[1].interval_start == earlier


@requires_postgres
@pytest.mark.django_db
def test_get_recent_respects_limit() -> None:
    repo = DjangoAggregatedBarRepository()
    bars_to_save = tuple(_bar(interval_start=BASE + timedelta(minutes=i)) for i in range(5))
    repo.save_all(bars_to_save)

    result = repo.get_recent(timeframe=Timeframe.ONE_MINUTE, limit=2)

    assert len(result) == 2


@requires_postgres
@pytest.mark.django_db
def test_get_recent_filters_by_timeframe() -> None:
    repo = DjangoAggregatedBarRepository()
    repo.save_all((_bar(),))

    five_minute_bars = repo.get_recent(timeframe=Timeframe.FIVE_MINUTE)

    assert five_minute_bars == ()
