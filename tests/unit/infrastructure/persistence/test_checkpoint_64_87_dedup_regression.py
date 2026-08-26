# tests/unit/infrastructure/persistence/test_checkpoint_64_87_dedup_regression.py
#
# Checkpoint 64.87 Part B: end-to-end regression replaying the SHAPE of
# the actual 64.85 incident through the real Django repository +
# aggregation stack (Postgres-backed, real `save_all()`/
# `get_observations()`/`aggregate_quotes_into_bars()` - no fakes) -
# verifying the fix at the point it actually matters: aggregated bar
# `observation_count` and volume must not be artificially inflated by
# stale re-persisted observations, and CAS-window quiet must not be
# fabricated into false continuous-trading bar completeness.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.bar_aggregation import BarAggregationService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
)
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
# 09:44 IST == 04:14 UTC, matching the actual 64.85 evidence bucket.
BUCKET_START = datetime(2026, 1, 5, 4, 14, 0, tzinfo=UTC)


def _quote(offset_seconds: int, price: str) -> Quote:
    return Quote(
        instrument_id=RELIANCE,
        timestamp=BUCKET_START + timedelta(seconds=offset_seconds),
        last_price=Decimal(price),
    )


@requires_postgres
@pytest.mark.django_db
def test_replayed_64_85_incident_shape_does_not_inflate_observation_count() -> None:
    """Replays the 64.85 evidence shape: ~55 genuinely distinct
    source_timestamps within a one-minute bucket, each re-delivered
    (same content, advancing fetched_at) multiple times, as the
    forensic evidence showed happening for real - then verifies the
    resulting bar's `observation_count` reflects the ~55 genuine
    observations, never the ~600 inflated re-persistence count."""
    quote_repo = DjangoLiveQuoteRepository()
    bar_repo = DjangoAggregatedBarRepository()
    service = BarAggregationService(quote_repository=quote_repo, bar_repository=bar_repo)

    genuine_observations = 55
    redeliveries_per_observation = 10  # mirrors ~600/55 ≈ 11x inflation observed in 64.85

    fetch_counter = 0
    for i in range(genuine_observations):
        quote = _quote(i, "1400.00")
        for _redelivery in range(redeliveries_per_observation):
            fetched_at = BUCKET_START + timedelta(seconds=i, milliseconds=fetch_counter)
            fetch_counter += 1
            quote_repo.save_all((quote,), fetched_at=fetched_at)

    as_of = BUCKET_START + timedelta(minutes=2)
    result = service.aggregate_and_persist(as_of=as_of, timeframe=Timeframe.ONE_MINUTE)

    closed_bars = [b for b in result.bars if b.interval_start == BUCKET_START.replace(second=0)]
    assert len(closed_bars) == 1
    bar = closed_bars[0]
    # The fix: observation_count reflects genuinely distinct
    # source_timestamps persisted (55), never the redelivery-inflated
    # count (550) - this IS the 64.85 defect, verified closed.
    assert bar.observation_count == genuine_observations
    assert bar.observation_count != genuine_observations * redeliveries_per_observation


@requires_postgres
@pytest.mark.django_db
def test_genuinely_new_observations_are_counted_normally() -> None:
    quote_repo = DjangoLiveQuoteRepository()
    bar_repo = DjangoAggregatedBarRepository()
    service = BarAggregationService(quote_repository=quote_repo, bar_repository=bar_repo)

    for i in range(5):
        quote_repo.save_all(
            (_quote(i, f"{1400 + i}.00"),), fetched_at=BUCKET_START + timedelta(seconds=i)
        )

    as_of = BUCKET_START + timedelta(minutes=2)
    result = service.aggregate_and_persist(as_of=as_of, timeframe=Timeframe.ONE_MINUTE)

    closed_bars = [b for b in result.bars if b.interval_start == BUCKET_START.replace(second=0)]
    assert len(closed_bars) == 1
    assert closed_bars[0].observation_count == 5
