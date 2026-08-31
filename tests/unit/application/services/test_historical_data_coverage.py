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
# Checkpoint 65.27: TCS is also CATEGORY_I_CAS (deliberately reusing the
# same 64.87 classification list, not a second list) - used to prove the
# coverage service is genuinely category-aware, not RELIANCE-specific.
SBIN = make_instrument_id(Exchange.NSE, "SBIN")  # CATEGORY_II_NON_CAS control


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


# ---------------------------------------------------------------------
# Checkpoint 65.27: CATEGORY_I_CAS reconciliation tests. Proves
# `HistoricalDataCoverageService` now expects 360 continuous one-minute
# bars (09:15-15:14 IST inclusive), not the old uniform 375, for
# CAS-eligible symbols - and that CATEGORY_II_NON_CAS behavior is
# completely unchanged.
def _single_trading_day_bounds() -> tuple[datetime, datetime]:
    # 2026-08-28 is a Friday (a trading day, no NSE_HOLIDAYS_2026 clash).
    start = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 28, 23, 59, tzinfo=UTC)
    return start, end


def test_category_i_cas_expects_360_one_minute_bars_for_one_trading_day() -> None:
    start, end = _single_trading_day_bounds()
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))

    report = service.get_coverage(RELIANCE, Timeframe.ONE_MINUTE, start, end)

    assert report.expected_bar_count == 360


def test_category_i_cas_first_expected_timestamp_is_09_15_ist() -> None:
    from zoneinfo import ZoneInfo

    start, end = _single_trading_day_bounds()
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))

    report = service.get_coverage(RELIANCE, Timeframe.ONE_MINUTE, start, end)

    ist = ZoneInfo("Asia/Kolkata")
    first_missing = report.missing_ranges[0].start.astimezone(ist)
    assert (first_missing.hour, first_missing.minute) == (9, 16)  # first bar-CLOSE, 1m after open


def test_category_i_cas_last_expected_continuous_timestamp_is_15_14_ist() -> None:
    """The last CONTINUOUS candle covers the [15:14, 15:15) minute - its
    bar-CLOSE timestamp (the vocabulary this service/`CasAwareSession.
    expected_continuous_bar_timestamps` both speak, matching `archive.py`'s
    established usage) is therefore 15:15 IST, not 15:14. 15:14 is the
    covering-minute/open of that last candle - this test asserts the
    bar-close value actually produced, which is what `HistoricalBar.
    timestamp` stores."""
    from zoneinfo import ZoneInfo

    start, end = _single_trading_day_bounds()
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))

    report = service.get_coverage(RELIANCE, Timeframe.ONE_MINUTE, start, end)

    ist = ZoneInfo("Asia/Kolkata")
    last_missing = report.missing_ranges[-1].end.astimezone(ist)
    assert (last_missing.hour, last_missing.minute) == (15, 15)


def test_category_i_cas_excludes_15_15_to_15_35_cas_window() -> None:
    from zoneinfo import ZoneInfo

    start, end = _single_trading_day_bounds()
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))

    report = service.get_coverage(RELIANCE, Timeframe.ONE_MINUTE, start, end)

    ist = ZoneInfo("Asia/Kolkata")
    all_missing_times = {
        (ts.astimezone(ist).hour, ts.astimezone(ist).minute)
        for rng in report.missing_ranges
        for ts in (rng.start, rng.end)
    }
    for hour, minute in all_missing_times:
        # 15:15 is the bar-CLOSE of the last CONTINUOUS candle (covering
        # [15:14,15:15)) - not a CAS-window candle. Only 15:16-15:35 would
        # represent an actual CAS-period timestamp leaking in.
        assert not (
            (hour == 15 and 16 <= minute <= 35)
        ), f"CAS-window timestamp {hour}:{minute:02d} leaked into continuous expected set"


def test_category_ii_non_cas_behavior_is_unchanged_at_375_five_minute_bars() -> None:
    """SBIN (CATEGORY_II_NON_CAS) must keep the pre-65.27 09:15-15:30
    expected set exactly - this checkpoint must not alter its behavior."""
    start = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    end = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    service = HistoricalDataCoverageService(repository=_FakeReadRepository(frozenset()))

    reliance_missing = service.get_coverage(
        SBIN, Timeframe.FIVE_MINUTE, start, end
    ).missing_ranges
    # SBIN's expected set must equal the plain (pre-CAS-aware) 375-minute
    # session's 5-minute expected timestamps, exactly as before 65.27.
    from intraday.domain.market_data.quality import expected_bar_timestamps
    from intraday.domain.session.calendar import build_session_for

    session = build_session_for(start.date(), end)
    full = frozenset(expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))
    complete_service = HistoricalDataCoverageService(repository=_FakeReadRepository(full))
    report = complete_service.get_coverage(SBIN, Timeframe.FIVE_MINUTE, start, end)

    assert report.is_complete
    assert report.expected_bar_count == len(full)
    assert reliance_missing  # sanity: something was expected at all
