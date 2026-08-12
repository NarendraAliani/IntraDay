# File: src/intraday/domain/session/contracts.py
#
# Canonical trading-session contract (Checkpoint 5) — intraday-only,
# Indian cash-equity market hours. No exchange-calendar SERVICE and no
# market-hours computation exists here (Checkpoint 5 Section 19); only the
# shape of one already-determined session.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime

from intraday.domain.shared_kernel.contracts import Exchange, ensure_utc


class SessionStatus(enum.Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


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
