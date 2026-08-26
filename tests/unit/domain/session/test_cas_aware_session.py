# tests/unit/domain/session/test_cas_aware_session.py
#
# Checkpoint 64.87: coverage for the CAS-aware session-timing foundation
# (Part A). Verifies instrument classification, the CATEGORY_I_CAS vs
# CATEGORY_II_NON_CAS continuous-trading/CAS boundaries (including the
# exact-boundary instants: 15:14:59, 15:15:00, 15:29:59, 15:30:00,
# 15:34:59, 15:35:00 IST), and that this new query surface does not
# alter the EXISTING `TradingSession`/`SessionStatus` behavior at all.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from intraday.domain.session.calendar import (
    CATEGORY_I_CAS_SYMBOLS,
    build_cas_aware_session_for,
    build_session_for,
    cas_aware_session_for_instant,
    instrument_category_for,
)
from intraday.domain.session.contracts import InstrumentCategory, MarketSessionState

SESSION_DATE = date(2026, 1, 5)  # a Monday, trading day


def _as_of(hour: int, minute: int, second: int = 0) -> datetime:
    naive_ist = datetime(2026, 1, 5, hour, minute, second)
    return (naive_ist + timedelta(hours=-5, minutes=-30)).replace(tzinfo=UTC)


# --- Instrument classification -----------------------------------------


@pytest.mark.parametrize("symbol", ["HDFCBANK", "INFY", "RELIANCE", "TCS", "infy", "Tcs"])
def test_universe_symbols_are_category_i_cas(symbol: str) -> None:
    assert instrument_category_for(symbol) is InstrumentCategory.CATEGORY_I_CAS


def test_unknown_symbol_defaults_to_category_ii_non_cas() -> None:
    assert instrument_category_for("SOMEUNKNOWNSTOCK") is InstrumentCategory.CATEGORY_II_NON_CAS


def test_all_current_universe_symbols_classified() -> None:
    assert {"HDFCBANK", "INFY", "RELIANCE", "TCS"} == CATEGORY_I_CAS_SYMBOLS


# --- Category-I continuous trading / CAS boundaries ---------------------


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (9, 0, 0, MarketSessionState.PRE_OPEN),
        (9, 15, 0, MarketSessionState.CONTINUOUS_TRADING),
        (12, 0, 0, MarketSessionState.CONTINUOUS_TRADING),
        (15, 14, 59, MarketSessionState.CONTINUOUS_TRADING),
        (15, 15, 0, MarketSessionState.CAS),
        (15, 20, 0, MarketSessionState.CAS),
        (15, 29, 59, MarketSessionState.CAS),
        (15, 30, 0, MarketSessionState.CAS),
        (15, 34, 59, MarketSessionState.CAS),
        (15, 35, 0, MarketSessionState.POST_CAS_TRANSITION),
        (16, 0, 0, MarketSessionState.POST_CAS_TRANSITION),
    ],
)
def test_category_i_cas_boundaries(
    hour: int, minute: int, second: int, expected: MarketSessionState
) -> None:
    session = build_cas_aware_session_for(
        InstrumentCategory.CATEGORY_I_CAS, SESSION_DATE, _as_of(hour, minute, second)
    )
    assert session.state is expected


def test_category_i_cas_through_15_35() -> None:
    for minute in range(15, 35):
        session = build_cas_aware_session_for(
            InstrumentCategory.CATEGORY_I_CAS, SESSION_DATE, _as_of(15, minute, 0)
        )
        assert session.is_cas, f"expected CAS at 15:{minute:02d} IST"


def test_category_i_continuous_trading_before_15_15() -> None:
    for hour, minute in ((9, 15), (10, 0), (12, 30), (15, 0), (15, 14)):
        session = build_cas_aware_session_for(
            InstrumentCategory.CATEGORY_I_CAS, SESSION_DATE, _as_of(hour, minute, 0)
        )
        assert session.is_continuous_trading


# --- Category-II boundaries (unchanged 15:30 close, no CAS) -------------


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (9, 0, 0, MarketSessionState.PRE_OPEN),
        (9, 15, 0, MarketSessionState.CONTINUOUS_TRADING),
        (15, 15, 0, MarketSessionState.CONTINUOUS_TRADING),  # NOT CAS for Category II
        (15, 29, 59, MarketSessionState.CONTINUOUS_TRADING),
        (15, 30, 0, MarketSessionState.CONTINUOUS_TRADING),
        (15, 30, 1, MarketSessionState.CLOSED),
        (16, 0, 0, MarketSessionState.CLOSED),
    ],
)
def test_category_ii_boundaries(
    hour: int, minute: int, second: int, expected: MarketSessionState
) -> None:
    session = build_cas_aware_session_for(
        InstrumentCategory.CATEGORY_II_NON_CAS, SESSION_DATE, _as_of(hour, minute, second)
    )
    assert session.state is expected


def test_category_ii_continuous_trading_through_15_30() -> None:
    for hour, minute in ((9, 15), (12, 0), (15, 29), (15, 30)):
        session = build_cas_aware_session_for(
            InstrumentCategory.CATEGORY_II_NON_CAS, SESSION_DATE, _as_of(hour, minute, 0)
        )
        assert session.is_continuous_trading


def test_category_ii_never_reports_cas() -> None:
    for hour in range(9, 20):
        for minute in (0, 15, 30, 45):
            session = build_cas_aware_session_for(
                InstrumentCategory.CATEGORY_II_NON_CAS, SESSION_DATE, _as_of(hour, minute, 0)
            )
            assert not session.is_cas
    assert session.cas_start is None
    assert session.cas_end is None


# --- Closed / holiday behavior ------------------------------------------


def test_holiday_is_holiday_regardless_of_category() -> None:
    republic_day = date(2026, 1, 26)
    for category in (InstrumentCategory.CATEGORY_I_CAS, InstrumentCategory.CATEGORY_II_NON_CAS):
        as_of = _as_of_date(republic_day, 12, 0)
        session = build_cas_aware_session_for(category, republic_day, as_of)
        assert session.state is MarketSessionState.HOLIDAY
        assert session.is_market_closed


def _as_of_date(d: date, hour: int, minute: int) -> datetime:
    naive_ist = datetime(d.year, d.month, d.day, hour, minute)
    return (naive_ist + timedelta(hours=-5, minutes=-30)).replace(tzinfo=UTC)


def test_is_market_closed_true_for_closed_and_holiday_only() -> None:
    closed = build_cas_aware_session_for(
        InstrumentCategory.CATEGORY_II_NON_CAS, SESSION_DATE, _as_of(16, 0, 0)
    )
    assert closed.is_market_closed
    cas = build_cas_aware_session_for(
        InstrumentCategory.CATEGORY_I_CAS, SESSION_DATE, _as_of(15, 20, 0)
    )
    assert not cas.is_market_closed


# --- cas_aware_session_for_instant convenience wrapper -------------------


def test_cas_aware_session_for_instant_derives_ist_date() -> None:
    # 02:00 UTC on 2026-01-05 is 07:30 IST on 2026-01-05 (still same date)
    as_of = datetime(2026, 1, 5, 2, 0, tzinfo=UTC)
    session = cas_aware_session_for_instant(InstrumentCategory.CATEGORY_I_CAS, as_of)
    assert session.session_date == date(2026, 1, 5)
    assert session.state is MarketSessionState.PRE_OPEN


# --- Existing TradingSession/SessionStatus is untouched ------------------


def test_existing_session_status_and_trading_session_unchanged() -> None:
    session = build_session_for(SESSION_DATE, _as_of(15, 20, 0))
    # Pre-64.87 behavior: 15:20 IST is inside [square_off_deadline, market_close]
    # for the OLD uniform 15:30 close - status is CLOSING, unchanged.
    from intraday.domain.session.contracts import SessionStatus

    assert session.status is SessionStatus.CLOSING
    assert session.market_close == datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


# --- expected_continuous_bar_timestamps ----------------------------------


def test_expected_continuous_bar_timestamps_bounded_by_continuous_close_not_cas() -> None:
    session = build_cas_aware_session_for(
        InstrumentCategory.CATEGORY_I_CAS, SESSION_DATE, _as_of(15, 20, 0)
    )
    timestamps = session.expected_continuous_bar_timestamps(timedelta(minutes=1))
    assert timestamps[-1] == session.continuous_trading_close
    assert all(ts <= session.continuous_trading_close for ts in timestamps)
    # 09:15 -> 15:15 continuous window == 360 one-minute bars
    assert len(timestamps) == 360
