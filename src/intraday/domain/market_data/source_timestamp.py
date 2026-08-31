# File: src/intraday/domain/market_data/source_timestamp.py
#
# Checkpoint 67.1 Part 2 — the smallest reusable representation needed
# to distinguish a market-data PROVIDER's raw candle-timestamp
# convention from this application's own canonical contract
# (`Bar.timestamp` = bar-CLOSE, UTC — see `domain.market_data.
# contracts.Bar`'s own docstring).
#
# WHY THIS EXISTS: Checkpoint 67.0 conclusively proved, for Dhan's
# `/v2/charts/intraday` endpoint (RELIANCE, 2026-08-17, 5m, 15/15
# interior-bucket OPEN-aggregation matches, 0/15 CLOSE matches — see
# that checkpoint's `taskReport.md`), that Dhan's raw intraday candle
# timestamp is OPEN-of-interval, not CLOSE-of-interval. The previous
# adapter code (`historical_provider.py::_candle_to_bar`) copied that
# raw timestamp into `Bar.timestamp` with NO transform — a silent
# mislabeling. This module is deliberately NOT Dhan-specific: any
# future provider (a second broker, a vendor feed, a CSV import) has
# its own timestamp convention, which may be OPEN, CLOSE, or simply
# not yet established for that endpoint — so callers must state it
# explicitly rather than a default silently meaning "assume OPEN" or
# "assume CLOSE".
#
# DELIBERATELY SMALL: this is one enum plus one pure function, not a
# new Bar variant or a parallel timestamp-bearing dataclass — Part 2's
# explicit instruction to "avoid creating an unnecessary large
# abstraction." `ProvenancedBar` (research_bar.py) is a precedent for
# how this codebase already prefers a thin, additive wrapper over
# reshaping `Bar` itself.
from __future__ import annotations

import enum
from datetime import datetime, timedelta


class SourceTimestampSemantics(enum.Enum):
    """What a provider's raw candle timestamp represents, relative to
    the interval it labels. Exhaustive and explicit — there is
    deliberately no default member and no "most likely" fallback: a
    provider/endpoint whose convention has not been empirically
    established (67.0's discipline — only the tested endpoint/interval
    combination is asserted) must be classified UNKNOWN, never silently
    treated as OPEN or CLOSE."""

    OPEN = "OPEN"
    """Raw timestamp T represents the interval [T, T + interval)."""

    CLOSE = "CLOSE"
    """Raw timestamp T already represents this application's canonical
    bar-close contract — no transform needed."""

    UNKNOWN = "UNKNOWN"
    """Not empirically established for this provider/endpoint. Passing
    this to `canonicalize_close_timestamp` always raises — there is no
    silent default, per Checkpoint 67.1 Part 6 test case 8."""


class UnknownSourceTimestampSemanticsError(ValueError):
    """Raised by `canonicalize_close_timestamp` when asked to
    canonicalize a raw timestamp whose semantics are `UNKNOWN`. A
    provider must classify its convention (via empirical proof, as
    67.0 did for Dhan intraday) before any bar derived from it can be
    persisted under this application's canonical bar-close contract."""


def canonicalize_close_timestamp(
    raw_timestamp: datetime,
    semantics: SourceTimestampSemantics,
    interval_duration: timedelta,
) -> datetime:
    """Convert one provider-raw candle timestamp into this
    application's canonical bar-CLOSE timestamp. Pure arithmetic,
    generic across every interval (1m/5m/15m/1h/1d) — the caller
    supplies `interval_duration`, this function never hard-codes a
    clock time, symbol, or category (mirrors `_provider_request_
    envelope`'s existing "pure bar-duration arithmetic" discipline in
    `historical_provider.py`).

    OPEN  -> raw_timestamp + interval_duration  (67.0's proven Dhan
             intraday case: canonical_close = source_open + interval).
    CLOSE -> raw_timestamp unchanged (already canonical).
    UNKNOWN -> raises `UnknownSourceTimestampSemanticsError` — never a
             silent OPEN assumption (Part 6 test case 8)."""
    if semantics is SourceTimestampSemantics.OPEN:
        return raw_timestamp + interval_duration
    if semantics is SourceTimestampSemantics.CLOSE:
        return raw_timestamp
    raise UnknownSourceTimestampSemanticsError(
        "cannot canonicalize a raw timestamp whose provider semantics are "
        "UNKNOWN — classify the provider/endpoint's convention first "
        "(empirically, as Checkpoint 67.0 did for Dhan intraday) rather "
        "than silently assuming OPEN or CLOSE."
    )


__all__ = [
    "SourceTimestampSemantics",
    "UnknownSourceTimestampSemanticsError",
    "canonicalize_close_timestamp",
]
