# tests/unit/infrastructure/persistence/test_historical_bar_repository.py
#
# Checkpoint 63.x Phase 2/28/36 test #8: real Django ORM coverage for
# `DjangoHistoricalBarRepository` - proves the uniqueness rule (Phase 2:
# "instrument + timeframe + bar timestamp", NEVER the row id) actually
# prevents duplicate rows on re-persistence, and that `get_bars()`
# (satisfying the pre-existing `HistoricalMarketDataRepository` Protocol)
# returns bars in chronological order.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


def _bar(ts: datetime, close: str = "100.00") -> Bar:
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=ts,
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("90.00"),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


@requires_postgres
@pytest.mark.django_db
def test_bulk_upsert_persists_new_bars() -> None:
    repo = DjangoHistoricalBarRepository()
    bars = (
        _bar(datetime(2026, 1, 5, 4, 0, tzinfo=UTC)),
        _bar(datetime(2026, 1, 5, 4, 5, tzinfo=UTC)),
    )

    written = repo.bulk_upsert(bars, source="API_FETCH")

    assert written == 2
    assert HistoricalBar.objects.count() == 2


@requires_postgres
@pytest.mark.django_db
def test_re_persisting_the_same_bar_does_not_create_a_duplicate_row() -> None:
    """Phase 2's uniqueness rule, proven end to end: re-fetching an
    already-cached bar must upsert in place, never duplicate."""
    repo = DjangoHistoricalBarRepository()
    ts = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
    repo.bulk_upsert((_bar(ts, close="100.00"),), source="API_FETCH")
    repo.bulk_upsert(
        (_bar(ts, close="105.00"),), source="API_FETCH"
    )  # revised value, same identity

    assert HistoricalBar.objects.count() == 1
    row = HistoricalBar.objects.get()
    assert row.close_price == Decimal("105.00")  # the later upsert won, not a stale duplicate


@requires_postgres
@pytest.mark.django_db
def test_get_bars_returns_chronological_order_satisfying_the_read_protocol() -> None:
    repo = DjangoHistoricalBarRepository()
    later = datetime(2026, 1, 5, 4, 10, tzinfo=UTC)
    earlier = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
    repo.bulk_upsert((_bar(later), _bar(earlier)), source="API_FETCH")  # inserted out of order

    bars = repo.get_bars(RELIANCE, Timeframe.FIVE_MINUTE, earlier, later)

    assert [b.timestamp for b in bars] == [earlier, later]


@requires_postgres
@pytest.mark.django_db
def test_get_existing_timestamps_only_returns_the_requested_range() -> None:
    repo = DjangoHistoricalBarRepository()
    inside = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
    outside = datetime(2026, 1, 6, 4, 0, tzinfo=UTC)
    repo.bulk_upsert((_bar(inside), _bar(outside)), source="API_FETCH")

    timestamps = repo.get_existing_timestamps(
        RELIANCE,
        Timeframe.FIVE_MINUTE,
        datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
    )

    assert timestamps == frozenset({inside})
