# File: src/intraday/domain/market_data/quality.py
#
# Checkpoint 14: pure, technology-neutral market-data integrity functions
# — ordering/duplicate validation and deterministic missing-interval
# detection over a `Bar` series. Domain-layer, not application-layer,
# because these rules are intrinsic to what a valid Bar *series* means
# (the same way `Bar.__post_init__` validates what a valid single Bar
# means) and must be identically true for research/backtesting and live
# consumers alike (Rule 5.5 parity) — no infrastructure, no provider
# knowledge, no Django import.
#
# Policy (Checkpoint 14 §16, §6): invalid ordering is REJECTED (raises),
# never silently discarded or silently reordered. A caller that wants
# resilience against a misbehaving provider must catch these exceptions
# explicitly at the infrastructure boundary — the domain layer never
# guesses what "fixing" bad data would mean.
from __future__ import annotations

from datetime import datetime, timedelta

from intraday.domain.market_data.contracts import Bar
from intraday.domain.session.contracts import TradingSession
from intraday.domain.shared_kernel.contracts import Timeframe


class DuplicateBarTimestampError(ValueError):
    """Raised when two bars in a series share the same timestamp."""


class OutOfOrderBarError(ValueError):
    """Raised when a bar series is not strictly increasing by timestamp."""


def ensure_chronological(bars: tuple[Bar, ...]) -> tuple[Bar, ...]:
    """Validates that `bars` is strictly increasing by `timestamp` with no
    duplicates, and returns it unchanged if so. Never reorders or drops a
    bar itself — an out-of-order or duplicate series is a REJECTED input
    (Checkpoint 14 §16), the caller's responsibility to fix upstream, not
    this function's to paper over silently."""
    for previous, current in zip(bars, bars[1:], strict=False):
        if current.timestamp == previous.timestamp:
            raise DuplicateBarTimestampError(
                f"duplicate bar timestamp {current.timestamp.isoformat()} "
                f"for instrument {current.instrument_id!r}"
            )
        if current.timestamp < previous.timestamp:
            raise OutOfOrderBarError(
                f"bar at {current.timestamp.isoformat()} follows "
                f"{previous.timestamp.isoformat()} out of order for "
                f"instrument {current.instrument_id!r}"
            )
    return bars


def timeframe_to_timedelta(timeframe: Timeframe) -> timedelta:
    """The fixed duration one bar of `timeframe` spans. `TICK` has no
    fixed duration by definition (a tick is a single trade/quote event,
    not a time bucket) and deliberately raises rather than returning an
    arbitrary placeholder."""
    mapping = {
        Timeframe.ONE_MINUTE: timedelta(minutes=1),
        Timeframe.THREE_MINUTE: timedelta(minutes=3),
        Timeframe.FIVE_MINUTE: timedelta(minutes=5),
        Timeframe.FIFTEEN_MINUTE: timedelta(minutes=15),
        Timeframe.THIRTY_MINUTE: timedelta(minutes=30),
        Timeframe.ONE_HOUR: timedelta(hours=1),
        Timeframe.DAY: timedelta(days=1),
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise ValueError(f"{timeframe!r} has no fixed bar duration") from exc


def expected_bar_timestamps(session: TradingSession, timeframe: Timeframe) -> tuple[datetime, ...]:
    """Every bar-close timestamp a complete, gap-free series for
    `timeframe` would have within `session` — deterministic arithmetic
    over the session's own already-determined open/close bounds, never a
    calendar computation (Checkpoint 14 §11). The first expected
    timestamp is `market_open + timeframe duration` (a bar's timestamp is
    its CLOSE time — see `Bar`'s docstring — so the bar covering
    [market_open, market_open + duration) closes at that instant, not at
    market_open itself)."""
    duration = timeframe_to_timedelta(timeframe)
    timestamps: list[datetime] = []
    current = session.market_open + duration
    while current <= session.market_close:
        timestamps.append(current)
        current += duration
    return tuple(timestamps)


def missing_bar_timestamps(
    bars: tuple[Bar, ...], session: TradingSession, timeframe: Timeframe
) -> tuple[datetime, ...]:
    """Which expected timestamps (per `expected_bar_timestamps`) are
    absent from `bars`. Deterministic and order-independent — does not
    require `bars` to already be validated chronological, so it can also
    diagnose a series before deciding whether to call
    `ensure_chronological` on it."""
    present = {bar.timestamp for bar in bars}
    return tuple(ts for ts in expected_bar_timestamps(session, timeframe) if ts not in present)
