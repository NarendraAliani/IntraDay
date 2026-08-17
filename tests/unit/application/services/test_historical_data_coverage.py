# tests/unit/application/services/test_historical_data_coverage.py
#
# Checkpoint 63.x Phase 3/4/36 test #6/#7: proves coverage detection is
# genuinely date/time-aware ("some rows exist" != "data is complete"),
# correctly identifies exact missing sub-ranges (not "some data is
# missing"), and never treats existing coverage as needing a refetch.
# Pure unit test - an in-memory fake `HistoricalBarReadRepository`, no
# database.
from __future__ import annotations

from datetime import UTC, datetime

from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


class _FakeReadRepository:
    def __init__(self, timestamps: frozenset[datetime]) -> None:
        self._timestamps = timestamps

    def get_existing_timestamps(
        self, instrument_id: object, timeframe: object, start: datetime, end: datetime
    ) -> frozenset[datetime]:
        return frozenset(ts for ts in self._timestamps if start <= ts <= end)


def test_empty_database_reports_zero_coverage_and_one_missing_range() -> None:
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))
    start = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    end = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)

    report = service.get_coverage(RELIANCE, Timeframe.FIVE_MINUTE, start, end)

    assert report.coverage_percent == 0.0
    assert not report.is_complete
    assert report.cached_bar_count == 0
    assert len(report.missing_ranges) == 1


def test_fully_cached_range_is_complete_with_zero_missing_ranges() -> None:
    start = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    end = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    # Build the exact expected timestamp set the way the service itself would.
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))
    expected = service.get_coverage(RELIANCE, Timeframe.FIVE_MINUTE, start, end).missing_ranges
    assert expected  # sanity: there IS something expected on a real trading day

    # Now build a repository containing every expected timestamp.
    from intraday.domain.market_data.quality import expected_bar_timestamps
    from intraday.domain.session.calendar import build_session_for

    session = build_session_for(start.date(), end)
    full = frozenset(expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))
    complete_service = HistoricalDataCoverageService(repository=_FakeReadRepository(full))

    report = complete_service.get_coverage(RELIANCE, Timeframe.FIVE_MINUTE, start, end)

    assert report.is_complete
    assert report.coverage_percent == 100.0
    assert report.missing_ranges == ()


def test_partial_coverage_identifies_the_exact_missing_sub_range() -> None:
    """Mirrors Phase 3's worked example: cached Jan1-Jan10, missing
    Jan11-Jan14, cached again after - the gap must be reported as its
    OWN distinct missing range, not merged with the edges."""
    from intraday.domain.market_data.quality import expected_bar_timestamps
    from intraday.domain.session.calendar import build_session_for, is_trading_day

    start = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    end = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)  # 5 trading days, Mon-Fri

    now = end
    all_timestamps: set[datetime] = set()
    current = start.date()
    while current <= end.date():
        if is_trading_day(current):
            session = build_session_for(current, now)
            all_timestamps.update(expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))
        current = current.fromordinal(current.toordinal() + 1)

    ordered_days = sorted({ts.date() for ts in all_timestamps})
    assert len(ordered_days) >= 3
    missing_day = ordered_days[len(ordered_days) // 2]
    cached = frozenset(ts for ts in all_timestamps if ts.date() != missing_day)

    service = HistoricalDataCoverageService(repository=_FakeReadRepository(cached))
    report = service.get_coverage(RELIANCE, Timeframe.FIVE_MINUTE, start, end)

    assert not report.is_complete
    assert len(report.missing_ranges) == 1
    assert report.missing_ranges[0].start.date() == missing_day
    assert report.missing_ranges[0].end.date() == missing_day
    assert report.cached_bar_count > 0  # the surrounding days remain cached
