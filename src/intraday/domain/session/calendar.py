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

from intraday.domain.session.contracts import (
    CasAwareSession,
    InstrumentCategory,
    MarketSessionState,
    SessionStatus,
    TradingSession,
)
from intraday.domain.shared_kernel.contracts import Exchange, ensure_utc

INDIA_STANDARD_TIME = ZoneInfo("Asia/Kolkata")

# Checkpoint 39 Part D: NSE cash-equity trading holidays for calendar
# year 2026 - `VERIFIED_SECONDARY` (a direct fetch of nseindia.com's own
# "Exchange Communication - Holidays" page timed out this session; this
# list was retrieved via a secondary source, groww.in's own published
# NSE 2026 equity-segment holiday calendar, cross-corroborated by a
# separate search confirming "15 full trading holidays" for the equity
# segment in 2026 - MATCHES the 15 dates below). NOT primary-verified
# against nseindia.com directly - flagged for confirmation before this
# list is relied on for anything beyond PAPER-mode session gating.
# Deliberately a closed, checkpoint-scoped list (2026 only) rather than
# a generic multi-year calendar service - extending to future years is
# a future checkpoint's job once a reliable primary source is fetchable.
NSE_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 26),  # Republic Day
        date(2026, 3, 3),  # Holi
        date(2026, 3, 26),  # Shri Ram Navami
        date(2026, 3, 31),  # Shri Mahavir Jayanti
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
        date(2026, 5, 1),  # Maharashtra Day
        date(2026, 5, 28),  # Bakri Id
        date(2026, 6, 26),  # Muharram
        date(2026, 9, 14),  # Ganesh Chaturthi
        date(2026, 10, 2),  # Mahatma Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 10),  # Diwali-Balipratipada
        date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
        date(2026, 12, 25),  # Christmas
    }
)


def is_trading_day(session_date: date) -> bool:
    """A trading day is a weekday that is not an `NSE_HOLIDAYS_2026`
    date. Dates outside 2026 are NOT covered by this checkpoint's
    holiday list - `is_trading_day()` still correctly excludes weekends
    for any year, but a holiday outside 2026 will NOT be detected
    (documented limitation, not silently assumed correct)."""
    return session_date.weekday() < 5 and session_date not in NSE_HOLIDAYS_2026


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
#
# Checkpoint 64.87 SQUARE-OFF NOTE (directive-required analysis, NOT a
# change): 64.86 flagged that 15:20 now falls INSIDE the CAS window
# (15:15-15:35) for CATEGORY_I_CAS instruments. This constant is RISK-
# MANAGEMENT POLICY ("close intraday exposure with a safety buffer
# before the exchange stops taking normal orders"), not a market-session
# timing fact - it is deliberately expressed here as an offset from the
# OLD uniform 15:30 close because that is the one authoritative
# `TradingSession.market_close` every existing consumer (paper session
# admission, risk, `TradingSession.__post_init__`'s own
# `[market_open, square_off_deadline, market_close]` ordering
# invariant) already depends on - `TradingSession`/`SessionStatus`
# themselves are NOT modified by this checkpoint (see module docstring
# below). Whether 15:20 is still the RIGHT square-off buffer for a
# CAS-eligible instrument (continuous trading itself now ends at 15:15,
# five minutes before this deadline) is a real open question this
# checkpoint explicitly does NOT resolve - changing risk-management
# trading behavior is out of scope (checkpoint directive: "DO NOT
# silently change risk-management behavior"). Left unchanged, flagged
# for a future risk-policy checkpoint to revisit deliberately.
SQUARE_OFF_DEADLINE_IST = time(15, 20)

# ---------------------------------------------------------------------
# Checkpoint 64.87: CAS-aware session-timing constants and instrument
# classification (Part A of the checkpoint). ADDITIVE ONLY - everything
# above this line (`MARKET_OPEN_IST`, `MARKET_CLOSE_IST`,
# `SQUARE_OFF_DEADLINE_IST`, `build_session_for`, `session_for_instant`,
# `TradingSession`, `SessionStatus`) is UNCHANGED and continues to
# govern every existing consumer exactly as before. This section adds a
# NARROWER, separate query surface (`CasAwareSession`) for the new
# "does continuous-trading apply right now, for this instrument
# category" question 64.86 found the platform had no way to answer.
#
# CATEGORY_I_CAS: NSE's Closing Auction Session (CAS) circular ends
# CONTINUOUS trading at 15:15 IST for CAS-eligible cash-equity
# instruments, followed by a 15:15-15:35 IST closing-auction window.
# CATEGORY_II_NON_CAS: continuous trading unchanged, through 15:30 IST
# (identical to the existing `MARKET_CLOSE_IST`).
CATEGORY_I_CONTINUOUS_CLOSE_IST = time(15, 15)
CATEGORY_I_CAS_END_IST = time(15, 35)
CATEGORY_II_CONTINUOUS_CLOSE_IST = MARKET_CLOSE_IST  # 15:30 IST, unchanged

# Checkpoint 65.33: the calendar date NSE's CAS circular actually took
# effect. Used ONLY by `domain.session.resolver.resolve_market_session`
# to distinguish the `Regime.PRE_CAS` / `Regime.CAS_ERA` eras — it is
# NOT a clock-time boundary (15:15/15:35 remain the intraday CAS
# boundaries, unchanged above) and does not alter
# `build_cas_aware_session_for()`'s own computation for any date: that
# function has always computed a `CasAwareSession` for CATEGORY_I_CAS
# instruments regardless of era, per its own long-standing documented
# scope. `CAS_EFFECTIVE_DATE` only lets a caller ask "was CAS actually
# running yet on this historical date," which `CasAwareSession` alone
# cannot answer.
CAS_EFFECTIVE_DATE = date(2026, 8, 3)

# Checkpoint 64.87: the current live observation universe (Checkpoint
# 23's four-symbol universe - see `docs/architecture/
# LIVE_MARKET_DATA_ARCHITECTURE.md`), classified CATEGORY_I_CAS. All
# four (HDFCBANK, INFY, RELIANCE, TCS) are highly liquid, F&O-eligible
# NSE large-caps and are CAS-eligible under NSE's circular. Deliberately
# a closed, checkpoint-scoped classification list (mirrors
# `NSE_HOLIDAYS_2026`'s own precedent) rather than a general reference-
# data service - "independent reference data" is explicitly out of
# scope for this checkpoint. A symbol not in this set is classified
# CATEGORY_II_NON_CAS by default (the safe default: continuous trading
# through 15:30, matching this codebase's PRE-64.87 uniform behavior).
CATEGORY_I_CAS_SYMBOLS: frozenset[str] = frozenset({"HDFCBANK", "INFY", "RELIANCE", "TCS"})


def instrument_category_for(symbol: str) -> InstrumentCategory:
    """Classifies a bare NSE cash-equity trading symbol (e.g. `"INFY"`,
    not an `InstrumentId`) into `InstrumentCategory`. Case-insensitive.
    See `CATEGORY_I_CAS_SYMBOLS`'s own docstring for the classification
    list and its documented limitation."""
    return (
        InstrumentCategory.CATEGORY_I_CAS
        if symbol.upper() in CATEGORY_I_CAS_SYMBOLS
        else InstrumentCategory.CATEGORY_II_NON_CAS
    )


def build_cas_aware_session_for(
    category: InstrumentCategory, session_date: date, as_of: datetime
) -> CasAwareSession:
    """Computes the `CasAwareSession` for `category` on `session_date`,
    classified against `as_of` (must be UTC). Mirrors `build_session_for`
    exactly in shape/holiday handling, but produces the narrower
    `MarketSessionState` state machine instead of `SessionStatus`."""
    ensure_utc(as_of, field_name="as_of")

    continuous_close_ist = (
        CATEGORY_I_CONTINUOUS_CLOSE_IST
        if category is InstrumentCategory.CATEGORY_I_CAS
        else CATEGORY_II_CONTINUOUS_CLOSE_IST
    )

    market_open = datetime.combine(
        session_date, MARKET_OPEN_IST, tzinfo=INDIA_STANDARD_TIME
    ).astimezone(UTC)
    continuous_close = datetime.combine(
        session_date, continuous_close_ist, tzinfo=INDIA_STANDARD_TIME
    ).astimezone(UTC)

    cas_start: datetime | None = None
    cas_end: datetime | None = None
    if category is InstrumentCategory.CATEGORY_I_CAS:
        cas_start = continuous_close
        cas_end = datetime.combine(
            session_date, CATEGORY_I_CAS_END_IST, tzinfo=INDIA_STANDARD_TIME
        ).astimezone(UTC)

    state = _classify_market_session_state(
        category=category,
        session_date=session_date,
        market_open=market_open,
        continuous_close=continuous_close,
        cas_end=cas_end,
        as_of=as_of,
    )

    return CasAwareSession(
        instrument_category=category,
        session_date=session_date,
        state=state,
        continuous_trading_open=market_open,
        continuous_trading_close=continuous_close,
        cas_start=cas_start,
        cas_end=cas_end,
    )


def _classify_market_session_state(
    *,
    category: InstrumentCategory,
    session_date: date,
    market_open: datetime,
    continuous_close: datetime,
    cas_end: datetime | None,
    as_of: datetime,
) -> MarketSessionState:
    if not is_trading_day(session_date):
        return MarketSessionState.HOLIDAY
    if as_of < market_open:
        return MarketSessionState.PRE_OPEN
    # Checkpoint 64.87 boundary convention: each window is a
    # HALF-OPEN [start, end) interval - the instant a window's END is
    # reached already belongs to the NEXT state. "Continuous Trading
    # 09:15-15:15" therefore means CONTINUOUS_TRADING while
    # `as_of < continuous_close` and CAS begins exactly AT 15:15:00 IST,
    # not one instant after it; symmetrically CAS ends exactly AT
    # 15:35:00 IST. (Deliberately NOT the older `SessionStatus`
    # convention of an inclusive closing boundary - CAS is a genuinely
    # NEW window that starts precisely when continuous trading's
    # published end time is reached, per NSE's CAS circular language of
    # "continuous trading ... up to 15:15 hours" immediately followed by
    # CAS.)
    if as_of < continuous_close:
        return MarketSessionState.CONTINUOUS_TRADING
    if category is InstrumentCategory.CATEGORY_II_NON_CAS:
        if as_of > continuous_close:
            return MarketSessionState.CLOSED
        return MarketSessionState.CONTINUOUS_TRADING
    assert cas_end is not None  # CATEGORY_I_CAS always carries a CAS window
    if as_of < cas_end:
        return MarketSessionState.CAS
    # Checkpoint 64.87: everything after CAS ends, for the REST of that
    # calendar date, is POST_CAS_TRANSITION - deliberately NOT further
    # subdivided into a separate terminal CLOSED instant for
    # CATEGORY_I_CAS. NSE has not published (and this checkpoint does
    # not invent) an authoritative "genuinely closed" boundary distinct
    # from "just past CAS" for a CAS-eligible instrument; a caller that
    # needs "closed" semantics for a CATEGORY_I_CAS instrument should
    # treat POST_CAS_TRANSITION as the terminal same-day state (the NEXT
    # trading day's PRE_OPEN is computed separately, for a different
    # `session_date`). This mirrors this module's own long-standing
    # "closed, checkpoint-scoped, documented limitation" style rather
    # than fabricating an unverified boundary.
    return MarketSessionState.POST_CAS_TRANSITION


def cas_aware_session_for_instant(category: InstrumentCategory, as_of: datetime) -> CasAwareSession:
    """Convenience wrapper mirroring `session_for_instant`: derives the
    correct IST calendar date for `as_of` (UTC) and builds that date's
    `CasAwareSession` for `category`."""
    ensure_utc(as_of, field_name="as_of")
    ist_date = as_of.astimezone(INDIA_STANDARD_TIME).date()
    return build_cas_aware_session_for(category, ist_date, as_of)


def build_session_for(session_date: date, as_of: datetime) -> TradingSession:
    """Computes the NSE cash-equity `TradingSession` for `session_date`,
    with `status` classified against `as_of` (must be UTC) - now
    holiday/weekend-aware (Checkpoint 39 Part D, closing Checkpoint 23's
    own documented "no holiday calendar" limitation for 2026 dates; see
    `NSE_HOLIDAYS_2026`'s own docstring for what remains unverified).
    `market_open`/`market_close`/`square_off_deadline` are still always
    computed (a `TradingSession` requires them structurally) even on a
    holiday - `status` is what tells a caller the date isn't actually
    tradable, never the shape's own presence/absence."""
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
        status=_classify(
            session_date=session_date,
            market_open=market_open,
            square_off_deadline=square_off_deadline,
            market_close=market_close,
            as_of=as_of,
        ),
    )


def _classify(
    *,
    session_date: date,
    market_open: datetime,
    square_off_deadline: datetime,
    market_close: datetime,
    as_of: datetime,
) -> SessionStatus:
    if not is_trading_day(session_date):
        return SessionStatus.HOLIDAY
    if as_of < market_open:
        return SessionStatus.PRE_OPEN
    if as_of > market_close:
        return SessionStatus.CLOSED
    if as_of >= square_off_deadline:
        return SessionStatus.CLOSING
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
