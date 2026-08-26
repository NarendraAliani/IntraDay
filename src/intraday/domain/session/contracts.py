# File: src/intraday/domain/session/contracts.py
#
# Canonical trading-session contract (Checkpoint 5) — intraday-only,
# Indian cash-equity market hours. No exchange-calendar SERVICE and no
# market-hours computation exists here (Checkpoint 5 Section 19); only the
# shape of one already-determined session.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from intraday.domain.shared_kernel.contracts import Exchange, ensure_utc


class SessionStatus(enum.Enum):
    """Checkpoint 39 Part D: extended from 3 to 5 states - `CLOSING`
    (the square-off window, `[square_off_deadline, market_close]`) and
    `HOLIDAY` (a calendar date with no session at all) are new. Every
    consumer of this enum (market-data ingestion, the risk engine,
    paper/future live execution, position monitoring, reporting) must
    treat `HOLIDAY` and `CLOSED` as BOTH meaning "no new order may be
    submitted" - they are distinguished only for operator/reporting
    clarity (why isn't the market open today?), never for different
    trading permissions."""

    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    HOLIDAY = "HOLIDAY"


@dataclass(frozen=True, slots=True)
class TradingSession:
    """One exchange's trading session for one calendar date.

    All instants are UTC internally (Checkpoint 3 §19) — IST wall-clock
    conversion for display happens only at the presentation boundary,
    never stored here. `square_off_deadline` enforces Rule 5.4 (mandatory
    intraday square-off): it must fall at or before `market_close`, giving
    `trading_engine/square_off` an unambiguous deadline to enforce.
    """

    session_date: date
    exchange: Exchange
    market_open: datetime
    market_close: datetime
    square_off_deadline: datetime
    status: SessionStatus

    def __post_init__(self) -> None:
        ensure_utc(self.market_open, field_name="TradingSession.market_open")
        ensure_utc(self.market_close, field_name="TradingSession.market_close")
        ensure_utc(self.square_off_deadline, field_name="TradingSession.square_off_deadline")
        if self.market_close <= self.market_open:
            raise ValueError("TradingSession.market_close must be after market_open")
        if not (self.market_open <= self.square_off_deadline <= self.market_close):
            raise ValueError(
                "TradingSession.square_off_deadline must fall within " "[market_open, market_close]"
            )

    def contains(self, timestamp: datetime) -> bool:
        """Checkpoint 14: whether `timestamp` (UTC) falls within this
        already-determined session's [market_open, market_close] bounds
        (inclusive) — the deterministic building block future market-data
        completeness/gap checks need ("does this bar's timestamp belong
        to this session?"), without this contract computing exchange
        calendars or session boundaries itself (Checkpoint 5 Section 19,
        unchanged: this remains the shape of one already-determined
        session, not a calendar service)."""
        ensure_utc(timestamp, field_name="timestamp")
        return self.market_open <= timestamp <= self.market_close


class InstrumentCategory(enum.Enum):
    """Checkpoint 64.87: which NSE cash-equity session-TIMING regime an
    instrument belongs to. NSE's Closing Auction Session (CAS) circular
    ends CONTINUOUS trading at 15:15 IST (not 15:30) for CAS-eligible
    ("Category I", broadly F&O-eligible/Category-I) instruments, followed
    by a 15:15-15:35 IST auction window; other ("Category II")
    cash-equity instruments keep continuous trading through 15:30 IST,
    unchanged.

    This is deliberately NOT an options/F&O trading subsystem — no
    contract, strike, expiry, OI, or Greeks concept is introduced here.
    It exists ONLY because cash-equity SESSION TIMING now differs by
    category; the classification is otherwise inert."""

    CATEGORY_I_CAS = "CATEGORY_I_CAS"
    CATEGORY_II_NON_CAS = "CATEGORY_II_NON_CAS"


class MarketSessionState(enum.Enum):
    """Checkpoint 64.87: fine-grained intraday session state, ADDITIVE
    alongside (never replacing) `SessionStatus` above. `SessionStatus`
    keeps governing order-admission-style questions ("can a paper order
    be accepted right now?") for every existing consumer (paper session,
    risk, archive) completely unchanged. `MarketSessionState` exists for
    a narrower, new question: "do CONTINUOUS-TRADING bar/tick
    expectations apply right now, for THIS instrument category?" —
    exactly the question 64.86 found the platform had no way to answer
    (the 64.85 "feed stall" could not be told apart from expected
    CAS quiet).

    `SessionStatus.OPEN` for a CATEGORY_I_CAS instrument is further
    subdivided here into CONTINUOUS_TRADING (09:15-15:15 IST) and CAS
    (15:15-15:35 IST) — both still fall inside `SessionStatus.OPEN`'s
    existing [market_open, market_close] bounds, so no existing
    `SessionStatus`/`TradingSession` consumer's behavior changes.

    PROVIDER-BEHAVIOR DISCLAIMER (mandatory, per 64.86/64.87): this state
    machine encodes EXCHANGE session semantics only — i.e. "continuous-
    trading bar/tick expectations do not apply during CAS." It makes NO
    claim about what Dhan's feed actually transmits during CAS (no
    packets at all, LTP-only updates, auction-related messages, or some
    other provider-specific behavior are all still open, unvalidated
    possibilities — see `docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md`
    's CAS provider-behavior open question). `MarketSessionState.CAS`
    must never be read as "no data will arrive."
    """

    PRE_OPEN = "PRE_OPEN"
    CONTINUOUS_TRADING = "CONTINUOUS_TRADING"
    CAS = "CAS"
    POST_CAS_TRANSITION = "POST_CAS_TRANSITION"
    CLOSED = "CLOSED"
    HOLIDAY = "HOLIDAY"


@dataclass(frozen=True, slots=True)
class CasAwareSession:
    """Checkpoint 64.87: the deterministic query surface consumers use to
    ask "what does exchange-session state say about THIS instrument
    category right now?" — the SESSION API the checkpoint directive
    requires (`current_session_state`, `is_continuous_trading`, `is_cas`,
    `is_market_closed`, `continuous_trading_window`). Computed by
    `domain.session.calendar.build_cas_aware_session_for` (this module
    stays the SHAPE-only contract, per its own module docstring — no
    market-hours computation here).

    Deliberately a SEPARATE type from `TradingSession`, not a
    replacement or subclass of it — `TradingSession`'s existing
    [market_open, market_close] bounds and `SessionStatus` are UNCHANGED
    by this checkpoint; this is an additive, narrower view for the new
    continuous-trading-vs-CAS question only."""

    instrument_category: InstrumentCategory
    session_date: date
    state: MarketSessionState
    continuous_trading_open: datetime
    continuous_trading_close: datetime
    cas_start: datetime | None
    cas_end: datetime | None

    def __post_init__(self) -> None:
        ensure_utc(
            self.continuous_trading_open, field_name="CasAwareSession.continuous_trading_open"
        )
        ensure_utc(
            self.continuous_trading_close, field_name="CasAwareSession.continuous_trading_close"
        )
        if self.continuous_trading_close <= self.continuous_trading_open:
            raise ValueError(
                "CasAwareSession.continuous_trading_close must be after " "continuous_trading_open"
            )
        if self.cas_start is not None:
            ensure_utc(self.cas_start, field_name="CasAwareSession.cas_start")
        if self.cas_end is not None:
            ensure_utc(self.cas_end, field_name="CasAwareSession.cas_end")
        if (self.cas_start is None) != (self.cas_end is None):
            raise ValueError("CasAwareSession.cas_start and cas_end must both be set or both None")
        if self.cas_start is not None and self.cas_end is not None:
            if self.cas_start != self.continuous_trading_close:
                raise ValueError("CasAwareSession.cas_start must equal continuous_trading_close")
            if self.cas_end <= self.cas_start:
                raise ValueError("CasAwareSession.cas_end must be after cas_start")
        if self.instrument_category is InstrumentCategory.CATEGORY_II_NON_CAS and (
            self.cas_start is not None or self.cas_end is not None
        ):
            raise ValueError("CATEGORY_II_NON_CAS sessions must not carry a CAS window")

    @property
    def current_session_state(self) -> MarketSessionState:
        return self.state

    @property
    def is_continuous_trading(self) -> bool:
        return self.state is MarketSessionState.CONTINUOUS_TRADING

    @property
    def is_cas(self) -> bool:
        return self.state is MarketSessionState.CAS

    @property
    def is_market_closed(self) -> bool:
        """`True` for both `CLOSED` and `HOLIDAY` — mirrors
        `SessionStatus`'s own documented "both mean no new order" stance
        (see `SessionStatus`'s docstring), applied here to the narrower
        "should continuous-trading data be expected" question."""
        return self.state in (MarketSessionState.CLOSED, MarketSessionState.HOLIDAY)

    def expected_continuous_bar_timestamps(self, bar_duration: timedelta) -> tuple[datetime, ...]:
        """Every bar-CLOSE timestamp a complete, gap-free series of
        `bar_duration`-wide bars would have within THIS session's
        continuous-trading window only — deliberately bounded by
        `continuous_trading_close`, never by a CAS or post-CAS instant,
        so a caller never expects an ordinary continuous-trading bar to
        exist for an interval that was actually CAS. Mirrors
        `domain.market_data.quality.expected_bar_timestamps`'s own
        arithmetic (duplicated rather than imported — `domain.session`
        must not depend on `domain.market_data`, the reverse of the
        existing, intentional dependency direction)."""
        if bar_duration <= timedelta(0):
            raise ValueError("bar_duration must be positive")
        timestamps: list[datetime] = []
        current = self.continuous_trading_open + bar_duration
        while current <= self.continuous_trading_close:
            timestamps.append(current)
            current += bar_duration
        return tuple(timestamps)
