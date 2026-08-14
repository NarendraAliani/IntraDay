# File: src/intraday/domain/session/calendar.py
#
# Checkpoint 23: the FIRST market-hours computation this codebase
# implements. `contracts.py`'s own docstring says "no market-hours
# computation exists here" — that was true through Checkpoint 22; this
# checkpoint explicitly authorizes the minimum session awareness needed
# for safe live-data observation (Checkpoint 23 §8). Kept as a separate
# pure-function module, mirroring `domain/market_data/quality.py`'s own
# split from `domain/market_data/contracts.py` — the *shape* of a
# session (`TradingSession`) stays in `contracts.py`; *computing* one is
# a distinct concern living here.
#
# Deliberately minimal (Checkpoint 23 §8's "minimum... necessary"):
# fixed NSE cash-equity intraday hours, no holiday calendar, no
# half-day/special-session handling. This is an explicit, documented
# limitation (see docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md),
# not an oversight — a full exchange holiday calendar is a separate,
# larger piece of work than "can we tell PRE_OPEN from OPEN from
# CLOSED today."
#
# `zoneinfo` (stdlib, no new dependency) is used for the one genuinely
# correct way to reason about India Standard Time — IST has no DST, but
# hand-computing a fixed UTC+5:30 offset in application code is exactly
# the "timezone logic scattered around" this checkpoint's brief warns
# against; a named zone keeps the IST/UTC boundary in one place.
from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, ensure_utc

INDIA_STANDARD_TIME = ZoneInfo("Asia/Kolkata")

# NSE/BSE cash-equity intraday hours (Checkpoint 23 §8) — fixed, not
# configuration-driven: these are exchange-mandated hours, not an
# operational parameter this platform's operator should be able to
# change via Settings (unlike the observation universe - §7, which
# genuinely is operator-configurable). No holiday calendar: a date that
# is actually a market holiday will still compute a session shape here
# (this is the explicit, documented limitation above) — callers must
# not assume "a session was computed" means "the market is actually
# open today."
MARKET_OPEN_IST = time(9, 15)
MARKET_CLOSE_IST = time(15, 30)
# Square-off deadline: 15:20 IST, ten minutes before market close - a
# conservative default matching common Indian intraday square-off
# convention (Rule 5.4's "mandatory intraday square-off"). No order-
# management code consumes this yet (Checkpoint 23 forbids that) - this
# field is populated because `TradingSession` requires it, not because
# anything acts on it this checkpoint.
SQUARE_OFF_DEADLINE_IST = time(15, 20)


def build_session_for(session_date: date, as_of: datetime) -> TradingSession:
    """Computes the (fixed-hours, no-holiday-aware) NSE cash-equity
    `TradingSession` for `session_date`, with `status` classified against
    `as_of` (must be UTC). This is the one place IST wall-clock hours are
    converted to the UTC instants `TradingSession` requires internally
    (Checkpoint 5's original decision, unchanged) - no other module
    should perform this conversion."""
    ensure_utc(as_of, field_name="as_of")

    market_open_ist = datetime.combine(session_date, MARKET_OPEN_IST, tzinfo=INDIA_STANDARD_TIME)
    market_close_ist = datetime.combine(session_date, MARKET_CLOSE_IST, tzinfo=INDIA_STANDARD_TIME)
    square_off_ist = datetime.combine(
        session_date, SQUARE_OFF_DEADLINE_IST, tzinfo=INDIA_STANDARD_TIME
    )

    market_open = market_open_ist.astimezone(UTC)
    market_close = market_close_ist.astimezone(UTC)
    square_off_deadline = square_off_ist.astimezone(UTC)

    return TradingSession(
        session_date=session_date,
        exchange=Exchange.NSE,
        market_open=market_open,
        market_close=market_close,
        square_off_deadline=square_off_deadline,
        status=_classify(market_open, market_close, as_of),
    )


def _classify(market_open: datetime, market_close: datetime, as_of: datetime) -> SessionStatus:
    if as_of < market_open:
        return SessionStatus.PRE_OPEN
    if as_of > market_close:
        return SessionStatus.CLOSED
    return SessionStatus.OPEN


def session_for_instant(as_of: datetime) -> TradingSession:
    """Convenience wrapper: derives the correct IST calendar date for
    `as_of` (UTC) and builds that date's session - the one place a
    caller needs "the session for right now" without separately having
    to convert UTC "now" to an IST calendar date itself (a naive
    `as_of.date()` would be wrong for the ~5.5 hours per day where the
    UTC and IST calendar dates differ, e.g. any time before 05:30 UTC)."""
    ensure_utc(as_of, field_name="as_of")
    ist_date = as_of.astimezone(INDIA_STANDARD_TIME).date()
    return build_session_for(ist_date, as_of)
