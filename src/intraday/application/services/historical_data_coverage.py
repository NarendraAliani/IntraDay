# File: src/intraday/application/services/historical_data_coverage.py
#
# Checkpoint 63.x Phase 3/4: the DATABASE COVERAGE step of the
# mandatory architecture
#
#     BACKTEST REQUEST -> DATABASE FIRST -> [COMPLETE: read] / [MISSING: fetch]
#
# This service answers exactly one question - "how much of the
# requested (instrument, timeframe, date range) is already in the
# database, and which sub-ranges are missing?" - and nothing else. It
# never fetches from an API and never scans; `HistoricalDataPreparationService`
# (the next step in the pipeline) is the only caller allowed to react to
# a non-empty `missing_ranges` by reaching for a provider.
#
# Deliberately date/time-aware, not row-count-aware (Phase 3's explicit
# warning: "do not treat 'some rows exist' as 'data is complete'"): a
# requested range is only "complete" when every expected bar-close
# timestamp - per the SAME `domain.market_data.quality.
# expected_bar_timestamps`/`domain.session.calendar.build_session_for`
# used everywhere else bar completeness is checked - is actually present
# in the database. Reuses that existing domain logic rather than
# re-implementing a second definition of "what timestamps should exist."
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from intraday.application.repositories.historical_bars import HistoricalBarReadRepository
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.domain.market_data.quality import expected_bar_timestamps, timeframe_to_timedelta
from intraday.domain.session.calendar import (
    build_cas_aware_session_for,
    build_session_for,
    instrument_category_for,
    is_trading_day,
)
from intraday.domain.session.contracts import InstrumentCategory
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc


@dataclass(frozen=True, slots=True)
class DateRange:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class CoverageReport:
    instrument_id: InstrumentId
    timeframe: Timeframe
    requested_start: datetime
    requested_end: datetime
    expected_bar_count: int
    cached_bar_count: int
    coverage_percent: float
    missing_ranges: tuple[DateRange, ...]
    cached_ranges: tuple[DateRange, ...]

    @property
    def is_complete(self) -> bool:
        return len(self.missing_ranges) == 0 and self.expected_bar_count > 0


def _expected_timestamps(
    start: datetime, end: datetime, timeframe: Timeframe, instrument_id: InstrumentId
) -> tuple[datetime, ...]:
    """Every bar-close timestamp a complete series would have across
    every trading day in `[start, end]` - built entirely from the
    already-established domain calendar/session machinery, never a
    second, parallel calendar implementation.

    Checkpoint 65.27: which session machinery depends on the
    instrument's `InstrumentCategory` (64.87/64.88's existing, reused
    model - NOT re-derived here). CATEGORY_I_CAS instruments (RELIANCE,
    HDFCBANK, INFY, TCS) end CONTINUOUS trading at 15:15 IST, followed
    by a 15:15-15:35 IST closing-auction window that is NOT an ordinary
    continuous one-minute OHLC interval - `build_cas_aware_session_for`
    + `CasAwareSession.expected_continuous_bar_timestamps` (the same
    CAS-aware pair `domain.market_data.archive.assess_archive_day`
    already uses for `AggregatedBarObservation`) is used for these,
    never the old uniform 09:15-15:30 `expected_bar_timestamps`.
    CATEGORY_II_NON_CAS instruments keep the prior, unchanged
    `build_session_for` + `expected_bar_timestamps` behavior - this
    checkpoint does not alter their expected set at all."""
    ensure_utc(start, field_name="start")
    ensure_utc(end, field_name="end")
    _, symbol = parse_instrument_id(instrument_id)
    category = instrument_category_for(symbol)
    timestamps: list[datetime] = []
    current_date: date = start.date()
    end_date: date = end.date()
    as_of = end  # session status classification is irrelevant here; only the shape matters
    while current_date <= end_date:
        if is_trading_day(current_date):
            if category is InstrumentCategory.CATEGORY_I_CAS:
                cas_session = build_cas_aware_session_for(category, current_date, as_of)
                try:
                    bar_duration = timeframe_to_timedelta(timeframe)
                except ValueError:
                    bar_duration = None
                day_timestamps = (
                    cas_session.expected_continuous_bar_timestamps(bar_duration)
                    if bar_duration is not None
                    else ()
                )
            else:
                session = build_session_for(current_date, as_of)
                day_timestamps = expected_bar_timestamps(session, timeframe)
            for ts in day_timestamps:
                if start <= ts <= end:
                    timestamps.append(ts)
        current_date += timedelta(days=1)
    return tuple(timestamps)


def _group_into_ranges(
    timestamps: tuple[datetime, ...], timeframe_delta: timedelta
) -> tuple[DateRange, ...]:
    """Collapses a sorted set of individual bar timestamps into
    contiguous `DateRange`s - two timestamps are "contiguous" if they
    are exactly one bar-duration apart. This is what turns "these 400
    individual 5-minute timestamps are missing" into the small number of
    human/API-meaningful gaps Phase 3's worked examples describe (e.g.
    "2026-02-16 -> 2026-03-31"), rather than one range per bar."""
    if not timestamps:
        return ()
    ordered = sorted(timestamps)
    ranges: list[DateRange] = []
    range_start = ordered[0]
    previous = ordered[0]
    for ts in ordered[1:]:
        if ts - previous > timeframe_delta:
            ranges.append(DateRange(start=range_start, end=previous))
            range_start = ts
        previous = ts
    ranges.append(DateRange(start=range_start, end=previous))
    return tuple(ranges)


@dataclass(frozen=True, slots=True)
class HistoricalDataCoverageService:
    """Application-layer coverage-detection service (Phase 4). Depends
    only on the `HistoricalBarReadRepository` Protocol - never a
    concrete Django model - matching every other application service in
    this codebase."""

    repository: HistoricalBarReadRepository

    def get_coverage(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> CoverageReport:
        expected = _expected_timestamps(start, end, timeframe, instrument_id)
        if not expected:
            return CoverageReport(
                instrument_id=instrument_id,
                timeframe=timeframe,
                requested_start=start,
                requested_end=end,
                expected_bar_count=0,
                cached_bar_count=0,
                coverage_percent=0.0,
                missing_ranges=(),
                cached_ranges=(),
            )

        existing = self.repository.get_existing_timestamps(instrument_id, timeframe, start, end)
        expected_set = set(expected)
        cached = tuple(sorted(ts for ts in expected if ts in existing))
        missing = tuple(sorted(ts for ts in expected if ts not in existing))
        delta = timeframe_to_timedelta(timeframe)

        coverage_percent = (
            round((len(cached) / len(expected_set)) * 100, 2) if expected_set else 0.0
        )

        return CoverageReport(
            instrument_id=instrument_id,
            timeframe=timeframe,
            requested_start=start,
            requested_end=end,
            expected_bar_count=len(expected_set),
            cached_bar_count=len(cached),
            coverage_percent=coverage_percent,
            missing_ranges=_group_into_ranges(missing, delta),
            cached_ranges=_group_into_ranges(cached, delta),
        )

    def is_complete(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> bool:
        return self.get_coverage(instrument_id, timeframe, start, end).is_complete

    def get_missing_ranges(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[DateRange, ...]:
        return self.get_coverage(instrument_id, timeframe, start, end).missing_ranges

    def get_cached_ranges(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[DateRange, ...]:
        return self.get_coverage(instrument_id, timeframe, start, end).cached_ranges
