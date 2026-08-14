# tests/unit/domain/session/test_calendar.py
#
# Checkpoint 23: coverage for the first market-hours computation this
# codebase implements - session boundary classification (PRE_OPEN/OPEN/
# CLOSED) and IST/UTC correctness, including the specific case a naive
# `as_of.date()` would get wrong (any UTC instant before 05:30, where
# the UTC and IST calendar dates differ).
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from intraday.domain.session.calendar import (
    MARKET_CLOSE_IST,
    MARKET_OPEN_IST,
    build_session_for,
    session_for_instant,
)
from intraday.domain.session.contracts import SessionStatus
from intraday.domain.shared_kernel.contracts import Exchange

SESSION_DATE = date(2026, 1, 5)  # a Monday


def test_market_open_is_09_15_ist_converted_to_utc() -> None:
    session = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 4, 0, tzinfo=UTC))

    # 09:15 IST == 03:45 UTC
    assert session.market_open == datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def test_market_close_is_15_30_ist_converted_to_utc() -> None:
    session = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 4, 0, tzinfo=UTC))

    # 15:30 IST == 10:00 UTC
    assert session.market_close == datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def test_square_off_deadline_is_before_market_close() -> None:
    session = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 4, 0, tzinfo=UTC))

    assert session.square_off_deadline < session.market_close
    assert session.square_off_deadline >= session.market_open


def test_exchange_is_nse() -> None:
    session = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 4, 0, tzinfo=UTC))

    assert session.exchange is Exchange.NSE


@pytest.mark.parametrize(
    ("as_of_ist_hour", "as_of_ist_minute", "expected_status"),
    [
        (6, 0, SessionStatus.PRE_OPEN),
        (9, 0, SessionStatus.PRE_OPEN),
        (9, 15, SessionStatus.OPEN),
        (12, 0, SessionStatus.OPEN),
        (15, 30, SessionStatus.OPEN),
        (15, 31, SessionStatus.CLOSED),
        (20, 0, SessionStatus.CLOSED),
    ],
)
def test_status_classification_boundaries(
    as_of_ist_hour: int, as_of_ist_minute: int, expected_status: SessionStatus
) -> None:
    # IST = UTC + 5:30 - construct the equivalent UTC instant directly.
    as_of_utc = datetime(2026, 1, 5, as_of_ist_hour, as_of_ist_minute, tzinfo=UTC) - _ist_offset()

    session = build_session_for(SESSION_DATE, as_of_utc)

    assert session.status is expected_status


def test_session_for_instant_uses_correct_ist_calendar_date_before_0530_utc() -> None:
    """01:00 UTC on 2026-01-05 is 06:30 IST on 2026-01-05 - same calendar
    date, unambiguous. The interesting case is 22:00 UTC on 2026-01-04,
    which is 03:30 IST on 2026-01-05 - a DIFFERENT calendar date. A naive
    `as_of.date()` would incorrectly compute the session for 2026-01-04."""
    as_of = datetime(2026, 1, 4, 22, 0, tzinfo=UTC)  # 03:30 IST, Jan 5

    session = session_for_instant(as_of)

    assert session.session_date == date(2026, 1, 5)
    assert session.status is SessionStatus.PRE_OPEN


def test_session_for_instant_requires_utc() -> None:
    from datetime import timedelta, timezone

    non_utc = datetime(2026, 1, 5, 4, 0, tzinfo=timezone(timedelta(hours=3)))
    with pytest.raises(ValueError, match="UTC"):
        session_for_instant(non_utc)


def test_market_open_and_close_constants_match_nse_cash_equity_hours() -> None:
    assert MARKET_OPEN_IST.hour == 9
    assert MARKET_OPEN_IST.minute == 15
    assert MARKET_CLOSE_IST.hour == 15
    assert MARKET_CLOSE_IST.minute == 30


def _ist_offset():  # type: ignore[no-untyped-def]
    from datetime import timedelta

    return timedelta(hours=5, minutes=30)
