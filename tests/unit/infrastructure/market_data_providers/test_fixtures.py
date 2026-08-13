# tests/unit/infrastructure/market_data_providers/test_fixtures.py
#
# Unit tests for FixtureHistoricalMarketDataRepository (Checkpoint 14) -
# pure Python, no database, no network, no credentials. Also the "proves
# the Protocol boundary works end-to-end" test: real
# HistoricalMarketDataService + real fixture repository together.
from __future__ import annotations

from datetime import UTC, datetime

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.market_data_providers.fixtures import (
    SYNTHETIC_INSTRUMENT_ID,
    FixtureHistoricalMarketDataRepository,
)

FAR_PAST = datetime(2000, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def test_fixture_repository_returns_deterministic_data() -> None:
    repo = FixtureHistoricalMarketDataRepository()

    first = repo.get_bars(SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE, FAR_PAST, FAR_FUTURE)
    second = repo.get_bars(SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE, FAR_PAST, FAR_FUTURE)

    assert first == second
    assert len(first) == 8


def test_fixture_repository_bars_are_already_chronological() -> None:
    repo = FixtureHistoricalMarketDataRepository()
    bars = repo.get_bars(SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE, FAR_PAST, FAR_FUTURE)

    timestamps = [bar.timestamp for bar in bars]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))


def test_fixture_repository_respects_the_requested_time_window() -> None:
    repo = FixtureHistoricalMarketDataRepository()
    narrow_start = datetime(2026, 1, 2, 3, 55, tzinfo=UTC)
    narrow_end = datetime(2026, 1, 2, 4, 5, tzinfo=UTC)

    bars = repo.get_bars(SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE, narrow_start, narrow_end)

    assert len(bars) == 3
    assert all(narrow_start <= bar.timestamp <= narrow_end for bar in bars)


def test_fixture_repository_returns_empty_for_unknown_instrument() -> None:
    repo = FixtureHistoricalMarketDataRepository()
    unknown = repo.get_bars(
        "NSE:DOES-NOT-EXIST",  # type: ignore[arg-type]
        Timeframe.FIVE_MINUTE,
        FAR_PAST,
        FAR_FUTURE,
    )
    assert unknown == ()


def test_service_and_fixture_repository_work_together_end_to_end() -> None:
    """The real contract boundary: the real `HistoricalMarketDataRepository`
    Protocol implementation, the real `HistoricalMarketDataService`, no
    mocking on either side."""
    service = HistoricalMarketDataService(repository=FixtureHistoricalMarketDataRepository())

    bars = service.get_bars(SYNTHETIC_INSTRUMENT_ID, Timeframe.FIVE_MINUTE, FAR_PAST, FAR_FUTURE)

    assert len(bars) == 8
    assert all(bar.instrument_id == SYNTHETIC_INSTRUMENT_ID for bar in bars)
