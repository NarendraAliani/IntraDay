# tests/unit/domain/test_market_data_quality.py
#
# Unit tests for the Checkpoint 14 market-data integrity functions:
# chronological/duplicate validation and deterministic missing-interval
# detection. Pure Python - no database, no Django, runs unconditionally.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import (
    DuplicateBarTimestampError,
    OutOfOrderBarError,
    ensure_chronological,
    expected_bar_timestamps,
    missing_bar_timestamps,
    timeframe_to_timedelta,
)
from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

INSTRUMENT = make_instrument_id(Exchange.NSE, "FIXTURE01")
OPEN = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
CLOSE = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)  # 15:30 IST


def _bar(timestamp: datetime) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1000"),
    )


def _session() -> TradingSession:
    return TradingSession(
        session_date=date(2026, 1, 1),
        exchange=Exchange.NSE,
        market_open=OPEN,
        market_close=CLOSE,
        square_off_deadline=CLOSE,
        status=SessionStatus.OPEN,
    )


# --- ensure_chronological ----------------------------------------------------


def test_ensure_chronological_accepts_strictly_increasing_series() -> None:
    bars = (_bar(OPEN + timedelta(minutes=5)), _bar(OPEN + timedelta(minutes=10)))
    assert ensure_chronological(bars) == bars


def test_ensure_chronological_accepts_empty_and_single_bar_series() -> None:
    assert ensure_chronological(()) == ()
    single = (_bar(OPEN + timedelta(minutes=5)),)
    assert ensure_chronological(single) == single


def test_ensure_chronological_rejects_duplicate_timestamps() -> None:
    bars = (_bar(OPEN + timedelta(minutes=5)), _bar(OPEN + timedelta(minutes=5)))
    with pytest.raises(DuplicateBarTimestampError):
        ensure_chronological(bars)


def test_ensure_chronological_rejects_out_of_order_series() -> None:
    bars = (_bar(OPEN + timedelta(minutes=10)), _bar(OPEN + timedelta(minutes=5)))
    with pytest.raises(OutOfOrderBarError):
        ensure_chronological(bars)


@given(
    offsets=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=30, unique=True)
)
def test_ensure_chronological_accepts_any_strictly_increasing_offsets(offsets: list[int]) -> None:
    ordered = sorted(offsets)
    bars = tuple(_bar(OPEN + timedelta(minutes=offset)) for offset in ordered)
    assert ensure_chronological(bars) == bars


# --- timeframe_to_timedelta ---------------------------------------------------


def test_timeframe_to_timedelta_five_minute() -> None:
    assert timeframe_to_timedelta(Timeframe.FIVE_MINUTE) == timedelta(minutes=5)


def test_timeframe_to_timedelta_one_day() -> None:
    assert timeframe_to_timedelta(Timeframe.DAY) == timedelta(days=1)


def test_timeframe_to_timedelta_rejects_tick() -> None:
    with pytest.raises(ValueError):
        timeframe_to_timedelta(Timeframe.TICK)


# --- expected_bar_timestamps / missing_bar_timestamps -------------------------


def test_expected_bar_timestamps_are_deterministic_and_close_time_stamped() -> None:
    session = _session()
    timestamps = expected_bar_timestamps(session, Timeframe.FIVE_MINUTE)
    # First expected bar closes 5 minutes after market open, not at open.
    assert timestamps[0] == session.market_open + timedelta(minutes=5)
    assert timestamps[-1] == session.market_close
    # Deterministic: recomputing gives the exact same result.
    assert expected_bar_timestamps(session, Timeframe.FIVE_MINUTE) == timestamps


def test_missing_bar_timestamps_is_empty_for_a_complete_series() -> None:
    session = _session()
    complete = tuple(_bar(ts) for ts in expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))
    assert missing_bar_timestamps(complete, session, Timeframe.FIVE_MINUTE) == ()


def test_missing_bar_timestamps_detects_a_real_gap() -> None:
    session = _session()
    expected = expected_bar_timestamps(session, Timeframe.FIVE_MINUTE)
    # Drop the third expected bar - a genuine gap in the middle of the session.
    incomplete = tuple(_bar(ts) for i, ts in enumerate(expected) if i != 2)
    missing = missing_bar_timestamps(incomplete, session, Timeframe.FIVE_MINUTE)
    assert missing == (expected[2],)


def test_missing_bar_timestamps_reports_deterministic_completeness_result() -> None:
    session = _session()
    partial = tuple(_bar(ts) for ts in expected_bar_timestamps(session, Timeframe.FIVE_MINUTE)[:3])
    first = missing_bar_timestamps(partial, session, Timeframe.FIVE_MINUTE)
    second = missing_bar_timestamps(partial, session, Timeframe.FIVE_MINUTE)
    assert first == second
    assert len(first) > 0
