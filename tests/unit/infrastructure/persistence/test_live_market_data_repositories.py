# tests/unit/infrastructure/persistence/test_live_market_data_repositories.py
#
# Checkpoint 23: Django ORM repository coverage - real persistence,
# real retrieval, singleton health-record behavior.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoLiveQuoteRepository,
    DjangoMarketDataHealthRepository,
)
from intraday.infrastructure.persistence.models import MarketDataHealthStatus
from tests.postgres_utils import requires_postgres

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _quote(symbol: str, price: str, timestamp: datetime = NOW) -> Quote:
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, symbol),
        timestamp=timestamp,
        last_price=Decimal(price),
    )


@requires_postgres
@pytest.mark.django_db
def test_get_latest_before_any_save_returns_empty() -> None:
    repo = DjangoLiveQuoteRepository()

    assert repo.get_latest() == ()


@requires_postgres
@pytest.mark.django_db
def test_save_then_get_latest_round_trips() -> None:
    repo = DjangoLiveQuoteRepository()

    repo.save_all((_quote("RELIANCE", "1234.56"),), fetched_at=NOW)

    latest = repo.get_latest()
    assert len(latest) == 1
    assert latest[0].last_price == Decimal("1234.56")
    assert str(latest[0].instrument_id) == "NSE:RELIANCE"


@requires_postgres
@pytest.mark.django_db
def test_get_latest_returns_the_most_recent_observation_per_instrument() -> None:
    repo = DjangoLiveQuoteRepository()
    earlier = NOW
    later = datetime(2026, 1, 5, 6, 5, tzinfo=UTC)

    repo.save_all((_quote("RELIANCE", "1000.00", earlier),), fetched_at=earlier)
    repo.save_all((_quote("RELIANCE", "1010.00", later),), fetched_at=later)

    latest = repo.get_latest()
    assert len(latest) == 1
    assert latest[0].last_price == Decimal("1010.00")


@requires_postgres
@pytest.mark.django_db
def test_get_latest_returns_one_entry_per_distinct_instrument() -> None:
    repo = DjangoLiveQuoteRepository()

    repo.save_all((_quote("RELIANCE", "1000.00"), _quote("TCS", "3500.00")), fetched_at=NOW)

    latest = repo.get_latest()
    assert len(latest) == 2
    symbols = {str(q.instrument_id) for q in latest}
    assert symbols == {"NSE:RELIANCE", "NSE:TCS"}


@requires_postgres
@pytest.mark.django_db
def test_save_all_is_append_only_never_overwrites_a_prior_row() -> None:
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    repo = DjangoLiveQuoteRepository()
    repo.save_all((_quote("RELIANCE", "1000.00"),), fetched_at=NOW)
    repo.save_all((_quote("RELIANCE", "1010.00"),), fetched_at=NOW)

    assert LiveQuoteObservation.objects.count() == 2


@requires_postgres
@pytest.mark.django_db
def test_save_all_skips_stale_duplicate_same_timestamp_same_snapshot() -> None:
    # Checkpoint 64.87 Part B: the exact 64.85 defect shape - the same
    # provider observation (same source_timestamp, same price) handed to
    # save_all() repeatedly (as fetched_at advances) must NOT be
    # re-persisted as if each call were a fresh market event.
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    repo = DjangoLiveQuoteRepository()
    later_fetch = datetime(2026, 1, 5, 6, 0, 1, tzinfo=UTC)

    repo.save_all((_quote("RELIANCE", "1000.00", NOW),), fetched_at=NOW)
    repo.save_all((_quote("RELIANCE", "1000.00", NOW),), fetched_at=later_fetch)
    repo.save_all((_quote("RELIANCE", "1000.00", NOW),), fetched_at=later_fetch)

    assert LiveQuoteObservation.objects.filter(instrument_symbol="RELIANCE").count() == 1


@requires_postgres
@pytest.mark.django_db
def test_save_all_persists_genuinely_new_source_timestamp() -> None:
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    repo = DjangoLiveQuoteRepository()
    t1 = NOW
    t2 = datetime(2026, 1, 5, 6, 0, 1, tzinfo=UTC)
    t3 = datetime(2026, 1, 5, 6, 0, 2, tzinfo=UTC)

    # Three legitimate observations, same price, three distinct
    # source_timestamps - all must survive (price equality alone is
    # never the dedup key).
    repo.save_all((_quote("RELIANCE", "1000.00", t1),), fetched_at=t1)
    repo.save_all((_quote("RELIANCE", "1000.00", t2),), fetched_at=t2)
    repo.save_all((_quote("RELIANCE", "1000.00", t3),), fetched_at=t3)

    assert LiveQuoteObservation.objects.filter(instrument_symbol="RELIANCE").count() == 3


@requires_postgres
@pytest.mark.django_db
def test_save_all_persists_conflicting_same_timestamp_different_price() -> None:
    # Different price at the same source_timestamp is an anomaly, not a
    # duplicate - never silently discarded.
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    repo = DjangoLiveQuoteRepository()

    repo.save_all((_quote("RELIANCE", "1000.00", NOW),), fetched_at=NOW)
    repo.save_all((_quote("RELIANCE", "1005.00", NOW),), fetched_at=NOW)

    assert LiveQuoteObservation.objects.filter(instrument_symbol="RELIANCE").count() == 2


@requires_postgres
@pytest.mark.django_db
def test_save_all_dedup_is_per_instrument() -> None:
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    repo = DjangoLiveQuoteRepository()

    repo.save_all(
        (_quote("RELIANCE", "1000.00", NOW), _quote("TCS", "3500.00", NOW)), fetched_at=NOW
    )
    repo.save_all(
        (_quote("RELIANCE", "1000.00", NOW), _quote("TCS", "3500.00", NOW)),
        fetched_at=datetime(2026, 1, 5, 6, 0, 1, tzinfo=UTC),
    )

    assert LiveQuoteObservation.objects.filter(instrument_symbol="RELIANCE").count() == 1
    assert LiveQuoteObservation.objects.filter(instrument_symbol="TCS").count() == 1


@requires_postgres
@pytest.mark.django_db
def test_health_get_before_any_record_returns_unconfigured_defaults() -> None:
    repo = DjangoMarketDataHealthRepository()

    record = repo.get()

    assert record.last_success_at is None
    assert record.consecutive_failures == 0


@requires_postgres
@pytest.mark.django_db
def test_health_record_success_resets_consecutive_failures() -> None:
    repo = DjangoMarketDataHealthRepository()
    repo.record_failure(checked_at=NOW, error_safe="Could not reach Dhan.")
    repo.record_failure(checked_at=NOW, error_safe="Could not reach Dhan.")

    repo.record_success(checked_at=NOW)

    record = repo.get()
    assert record.last_success_at == NOW
    assert record.consecutive_failures == 0


@requires_postgres
@pytest.mark.django_db
def test_health_record_failure_increments_consecutive_failures() -> None:
    repo = DjangoMarketDataHealthRepository()

    repo.record_failure(checked_at=NOW, error_safe="Could not reach Dhan.")
    repo.record_failure(checked_at=NOW, error_safe="Could not reach Dhan.")

    record = repo.get()
    assert record.consecutive_failures == 2
    assert record.last_error_safe == "Could not reach Dhan."


@requires_postgres
@pytest.mark.django_db
def test_health_repository_is_a_singleton() -> None:
    repo = DjangoMarketDataHealthRepository()
    repo.record_success(checked_at=NOW)
    repo.record_failure(checked_at=NOW, error_safe="x")

    assert MarketDataHealthStatus.objects.count() == 1
