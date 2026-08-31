# tests/unit/domain/session/test_resolver.py
#
# Checkpoint 65.33: focused coverage for the new
# `domain.session.resolver.resolve_market_session` composition layer.
# LIMITED, per checkpoint directive — covers PRE_CAS resolution,
# CAS_ERA resolution, the 15:15 boundary, CATEGORY_II_NON_CAS
# (non-CAS) behavior, and unknown/missing historical-eligibility
# behavior. Does not re-test `TradingSession`/`CasAwareSession`
# arithmetic itself (already covered by `test_calendar.py`/
# `test_cas_aware_session.py`) — only the NEW composition/regime/
# exit_eligible fields this checkpoint adds.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE
from intraday.domain.session.contracts import InstrumentCategory, MarketSessionState, SessionStatus
from intraday.domain.session.resolver import (
    HistoricalEligibility,
    Regime,
    resolve_market_session,
    resolve_market_session_for_instant,
)
from intraday.domain.shared_kernel.contracts import Exchange

CAS_ERA_DATE = date(2026, 8, 3)  # a Monday, trading day, on the effective date
PRE_CAS_DATE = date(2026, 1, 5)  # a Monday, trading day, before the effective date


def _as_of(session_date: date, hour: int, minute: int, second: int = 0) -> datetime:
    naive_ist = datetime(session_date.year, session_date.month, session_date.day, hour, minute, second)
    return (naive_ist + timedelta(hours=-5, minutes=-30)).replace(tzinfo=UTC)


# --- Regime: PRE_CAS vs CAS_ERA -----------------------------------------


def test_effective_date_constant_is_2026_08_03() -> None:
    assert CAS_EFFECTIVE_DATE == date(2026, 8, 3)


def test_date_before_effective_date_resolves_pre_cas() -> None:
    resolved = resolve_market_session(
        trading_date=PRE_CAS_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(PRE_CAS_DATE, 12, 0),
    )
    assert resolved.regime is Regime.PRE_CAS
    assert resolved.is_pre_cas is True
    assert resolved.is_cas_era is False


def test_date_on_effective_date_resolves_cas_era() -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(CAS_ERA_DATE, 12, 0),
    )
    assert resolved.regime is Regime.CAS_ERA
    assert resolved.is_cas_era is True
    assert resolved.is_pre_cas is False


def test_date_after_effective_date_resolves_cas_era() -> None:
    later_date = CAS_ERA_DATE + timedelta(days=30)
    # skip to a weekday to keep this a plain trading-day resolution
    while later_date.weekday() >= 5:
        later_date += timedelta(days=1)
    resolved = resolve_market_session(
        trading_date=later_date,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(later_date, 12, 0),
    )
    assert resolved.regime is Regime.CAS_ERA


# --- 15:15 boundary composition (delegates to CasAwareSession) ----------


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected_state"),
    [
        (15, 14, 59, MarketSessionState.CONTINUOUS_TRADING),
        (15, 15, 0, MarketSessionState.CAS),
    ],
)
def test_1515_boundary_is_reused_from_cas_aware_session(
    hour: int, minute: int, second: int, expected_state: MarketSessionState
) -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",  # CATEGORY_I_CAS
        as_of=_as_of(CAS_ERA_DATE, hour, minute, second),
    )
    assert resolved.instrument_category is InstrumentCategory.CATEGORY_I_CAS
    assert resolved.cas_session.state is expected_state


# --- CATEGORY_II_NON_CAS (non-CAS) instrument behavior -------------------


def test_non_cas_symbol_has_no_cas_window_regardless_of_regime() -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="SOMEUNKNOWNSTOCK",
        as_of=_as_of(CAS_ERA_DATE, 15, 20, 0),
    )
    assert resolved.instrument_category is InstrumentCategory.CATEGORY_II_NON_CAS
    assert resolved.cas_session.cas_start is None
    assert resolved.cas_session.cas_end is None
    assert resolved.cas_session.state is MarketSessionState.CONTINUOUS_TRADING
    # regime is still resolvable independent of instrument category
    assert resolved.regime is Regime.CAS_ERA


# --- Historical eligibility: explicit unknown state ----------------------


def test_default_is_known_current_not_historical() -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(CAS_ERA_DATE, 12, 0),
    )
    assert resolved.historical_eligibility is HistoricalEligibility.KNOWN_CURRENT
    assert resolved.historical_eligibility_unknown is False


def test_is_historical_true_yields_explicit_unknown_state() -> None:
    resolved = resolve_market_session(
        trading_date=PRE_CAS_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(PRE_CAS_DATE, 12, 0),
        is_historical=True,
    )
    assert resolved.historical_eligibility is HistoricalEligibility.UNKNOWN_HISTORICAL
    assert resolved.historical_eligibility_unknown is True
    # even with unknown historical eligibility, regime/timing composition
    # still resolves deterministically - only the ELIGIBILITY claim is
    # flagged unknown, not the whole resolution.
    assert resolved.regime is Regime.PRE_CAS
    assert resolved.trading_session.status is SessionStatus.OPEN


# --- exit_eligible: conservative, permissive default ---------------------


def test_exit_eligible_true_during_open_session() -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(CAS_ERA_DATE, 12, 0),
    )
    assert resolved.exit_eligible is True


def test_exit_eligible_true_during_cas_window() -> None:
    # 65.32's identified gap: existing-position exits are not currently
    # CAS-gated anywhere in the codebase - exit_eligible must not become
    # False just because the instrument is in its CAS window.
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(CAS_ERA_DATE, 15, 20, 0),
    )
    assert resolved.cas_session.state is MarketSessionState.CAS
    assert resolved.exit_eligible is True


def test_exit_eligible_false_when_market_closed() -> None:
    resolved = resolve_market_session(
        trading_date=CAS_ERA_DATE,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(CAS_ERA_DATE, 23, 0, 0),
    )
    assert resolved.trading_session.status is SessionStatus.CLOSED
    assert resolved.exit_eligible is False


def test_exit_eligible_false_on_holiday() -> None:
    holiday_date = date(2026, 1, 26)  # Republic Day, in NSE_HOLIDAYS_2026
    resolved = resolve_market_session(
        trading_date=holiday_date,
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=_as_of(holiday_date, 12, 0),
    )
    assert resolved.trading_session.status is SessionStatus.HOLIDAY
    assert resolved.exit_eligible is False


# --- resolve_market_session_for_instant convenience wrapper --------------


def test_resolve_for_instant_derives_correct_ist_date() -> None:
    # 03:00 UTC is 08:30 IST - still the SAME IST calendar date. Choosing
    # an instant just before IST midnight-crossing (18:35 UTC ~ 00:05 IST
    # next day) verifies the date derivation, mirroring
    # `session_for_instant`'s own established convention.
    as_of = datetime(2026, 8, 3, 3, 0, 0, tzinfo=UTC)  # 08:30 IST, same date
    resolved = resolve_market_session_for_instant(
        exchange=Exchange.NSE,
        segment="CASH_EQUITY",
        symbol="INFY",
        as_of=as_of,
    )
    assert resolved.trading_date == date(2026, 8, 3)
    assert resolved.regime is Regime.CAS_ERA
