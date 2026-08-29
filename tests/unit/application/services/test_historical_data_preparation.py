# tests/unit/application/services/test_historical_data_preparation.py
#
# Checkpoint 63.x Phase 5/6/22/36 tests #1/#2/#9/#17: proves the
# fetch-missing/validate/persist/verify sequence, bounded retries, and
# the mandatory Phase 22 "an already-complete range triggers ZERO
# provider calls" optimization. Pure unit test - fakes only, no
# database, no real provider.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
END = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


class _FakeReadRepository:
    def __init__(self) -> None:
        self.timestamps: set[datetime] = set()

    def get_existing_timestamps(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> frozenset[datetime]:
        return frozenset(ts for ts in self.timestamps if start <= ts <= end)


class _FakeWriteRepository:
    def __init__(self, read_repository: _FakeReadRepository) -> None:
        self._read = read_repository
        self.upsert_calls = 0

    def bulk_upsert(  # noqa: ARG002
        self, bars: tuple[Bar, ...], *, source: str, provenance: str = "UNKNOWN"
    ) -> int:
        self.upsert_calls += 1
        for bar in bars:
            self._read.timestamps.add(bar.timestamp)
        return len(bars)


def _bar(ts: datetime) -> Bar:
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1000"),
    )


class _AlwaysAvailableProvider:
    def __init__(self) -> None:
        self.fetch_calls = 0

    def fetch(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        self.fetch_calls += 1
        from intraday.domain.market_data.quality import expected_bar_timestamps
        from intraday.domain.session.calendar import build_session_for

        session = build_session_for(start.date(), end)
        return tuple(_bar(ts) for ts in expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))


class _UnavailableProvider:
    def __init__(self) -> None:
        self.fetch_calls = 0

    def fetch(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        self.fetch_calls += 1
        raise RuntimeError("provider unavailable")


def _service(read: _FakeReadRepository, provider: object) -> HistoricalDataPreparationService:
    write = _FakeWriteRepository(read)
    return HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=read), provider=provider, writer=write
    )


def test_missing_data_is_fetched_validated_and_persisted() -> None:
    read = _FakeReadRepository()
    provider = _AlwaysAvailableProvider()
    service = _service(read, provider)

    outcome = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert outcome.status == PreparationStatus.COMPLETE
    assert outcome.bars_fetched > 0
    assert outcome.bars_persisted == outcome.bars_fetched
    assert provider.fetch_calls == 1
    # verify persistence actually happened, not just claimed
    assert read.get_existing_timestamps(RELIANCE, Timeframe.FIVE_MINUTE, START, END)


def test_fully_cached_range_triggers_zero_provider_calls() -> None:
    """Phase 22's mandatory acceptance requirement: re-preparing an
    already-complete range must not call the provider at all."""
    read = _FakeReadRepository()
    provider = _AlwaysAvailableProvider()
    service = _service(read, provider)
    first = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)
    assert first.status == PreparationStatus.COMPLETE
    assert provider.fetch_calls == 1

    second = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert second.status == PreparationStatus.COMPLETE
    assert second.api_requests == 0
    assert second.bars_fetched == 0
    assert second.cache_hits == first.bars_persisted
    assert provider.fetch_calls == 1  # unchanged - the provider was never called again


def test_provider_unavailable_does_not_produce_a_falsely_complete_result() -> None:
    """Phase 6/23: an unreachable provider must never be silently
    treated as success - and must never leave a caller unable to tell
    the run failed to acquire the requested data."""
    read = _FakeReadRepository()
    provider = _UnavailableProvider()
    service = _service(read, provider)

    outcome = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert outcome.status == PreparationStatus.NOT_AVAILABLE
    assert outcome.bars_persisted == 0
    assert outcome.error_message != ""


def test_provider_failure_retries_are_bounded_not_infinite() -> None:
    read = _FakeReadRepository()
    provider = _UnavailableProvider()
    service = _service(read, provider)

    outcome = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    from intraday.application.services.historical_data_preparation import MAX_FETCH_ATTEMPTS

    assert provider.fetch_calls == MAX_FETCH_ATTEMPTS
    assert outcome.attempts == MAX_FETCH_ATTEMPTS
