# tests/unit/domain/test_market_data_timestamp_boundaries.py
#
# Checkpoint 31 Part 6: explicit clock/timestamp boundary validation.
# Pins the exact UTC<->IST conversions this project's TRADING_GRADE_BAR
# claims depend on, at the specific boundary instants the checkpoint
# names (09:15, 09:20, 15:25, 15:30 IST) plus 1-minute interval
# alignment - and cross-checks against the real, live Dhan API evidence
# gathered this checkpoint (see docs/research/TRADING_GRADE_BAR_VALIDATION.md
# Part 2): a genuine `POST /v2/charts/intraday` call for HDFCBANK on
# 2026-08-14 returned its first 1-minute candle's epoch timestamp as
# 1786679100 - which, interpreted as a standard UTC epoch, is exactly
# 2026-08-14 03:45:00 UTC == 2026-08-14 09:15:00 IST, i.e. the exact
# documented market-open instant. This is the empirical confirmation
# that closes Open Question #3 from
# docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md: Dhan's
# `/v2/charts/intraday` epoch timestamps are genuine UTC epoch values,
# not IST wall-clock time mislabeled as epoch.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.domain.market_data.aggregation import _interval_start
from intraday.domain.market_data.quality import timeframe_to_timedelta
from intraday.domain.session.calendar import INDIA_STANDARD_TIME, build_session_for
from intraday.domain.shared_kernel.contracts import Timeframe

SESSION_DATE = datetime(2026, 8, 14).date()


@pytest.mark.parametrize(
    ("ist_hour", "ist_minute", "expected_utc_hour", "expected_utc_minute"),
    [
        (9, 15, 3, 45),  # market open
        (9, 20, 3, 50),
        (15, 25, 9, 55),
        (15, 30, 10, 0),  # market close
    ],
)
def test_ist_to_utc_conversion_at_named_boundaries(
    ist_hour: int, ist_minute: int, expected_utc_hour: int, expected_utc_minute: int
) -> None:
    ist_instant = datetime(2026, 8, 14, ist_hour, ist_minute, tzinfo=INDIA_STANDARD_TIME)
    utc_instant = ist_instant.astimezone(UTC)

    assert utc_instant == datetime(2026, 8, 14, expected_utc_hour, expected_utc_minute, tzinfo=UTC)


def test_dhan_verified_epoch_matches_project_market_open_convention() -> None:
    """The exact epoch value observed from a real, live Dhan API call
    this checkpoint (1786679100.0, HDFCBANK, 2026-08-14's first intraday
    candle) - interpreted as standard UTC epoch - must equal this
    project's own computed market-open instant for that date. If Dhan's
    epoch convention were instead "IST wall-clock mislabeled as epoch,"
    this equality would be off by exactly 5 hours 30 minutes."""
    dhan_first_candle_epoch = 1786679100.0
    dhan_as_utc = datetime.fromtimestamp(dhan_first_candle_epoch, tz=UTC)

    session = build_session_for(SESSION_DATE, dhan_as_utc)

    assert dhan_as_utc == session.market_open


def test_interval_alignment_at_market_open_and_close() -> None:
    duration = timeframe_to_timedelta(Timeframe.ONE_MINUTE)
    market_open_utc = datetime(2026, 8, 14, 3, 45, tzinfo=UTC)
    market_close_utc = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

    assert _interval_start(market_open_utc, duration) == market_open_utc
    assert _interval_start(market_close_utc, duration) == market_close_utc


def test_interval_alignment_mid_interval_floors_to_interval_start() -> None:
    duration = timeframe_to_timedelta(Timeframe.ONE_MINUTE)
    mid_interval = datetime(2026, 8, 14, 3, 45, 37, tzinfo=UTC)  # 09:15:37 IST

    assert _interval_start(mid_interval, duration) == datetime(2026, 8, 14, 3, 45, tzinfo=UTC)


def test_no_silent_timezone_reinterpretation_naive_datetime_rejected() -> None:
    """The system must never silently reinterpret an ambiguous/naive
    timestamp as IST or UTC - `ensure_utc` (via `build_session_for`)
    rejects it outright."""
    naive = datetime(2026, 8, 14, 9, 15)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_session_for(SESSION_DATE, naive)  # type: ignore[arg-type]
