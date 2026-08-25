# File: src/intraday/infrastructure/market_data_providers/dhan/timestamp_normalization.py
#
# Checkpoint 64.71: THE ONE canonical conversion point for the Dhan
# LIVE MARKET FEED WEBSOCKET last-trade-time (LTT) epoch field.
#
# WHY THIS EXISTS (the 64.70 evidence, not a guess):
# Checkpoint 64.70 ran a real ~9.5-minute observe-only Dhan WebSocket
# session and recorded 2,154 real Ticker observations across four NSE
# symbols (HDFCBANK/INFY/RELIANCE/TCS) into `LiveQuoteObservation`
# (ids 72-2225). For EVERY one of those 2,154 rows, the decoded
# `source_timestamp` was AHEAD of `fetched_at` (the instant this
# process actually received the packet) by:
#
#     mean   19,799.250 s
#     median 19,799.26  s
#     stdev       0.385 s
#     min    19,797.271 s
#     max    19,799.990 s
#
# 19,800 s is EXACTLY 5h30m - the IST (Asia/Kolkata, UTC+05:30) offset.
# The spread is sub-second-to-2.7s, i.e. ordinary tick latency plus the
# LTT field's own 1-second wire resolution, NOT clock drift. That is a
# systematic labelling issue, not a variable one: Dhan's WebSocket LTT
# epoch counts seconds from the Unix epoch as if the WALL-CLOCK IST
# time were UTC. Reading it with `datetime.fromtimestamp(ltt, tz=UTC)`
# therefore yields an instant 5h30m in the FUTURE.
#
# CONSEQUENCE THIS FIXES: `domain/market_data/aggregation.py` correctly
# refuses any observation with `quote.timestamp > as_of` (a real safety
# check against future-dated data). Because 100% of live quotes were
# 5h30m in the future, 100% were rejected and ZERO bars formed during
# that entire live session. The fix belongs HERE, at the provider
# boundary, BEFORE the value ever enters the canonical market-data
# domain - the aggregation guard is correct and is deliberately left
# exactly as it is.
#
# SCOPE - DELIBERATELY NARROW. This applies ONLY to the Dhan WebSocket
# LTT epoch field decoded by `packet_decoder.py`. It does NOT apply to:
# Dhan REST timestamps, historical/candle data, the Backtest engine,
# synthetic providers, any other provider, or any already-stored
# database row. The canonical `Quote`/`Bar`/`AggregatedBar` timestamp
# CONTRACTS are unchanged - they still receive, as they always have, a
# timezone-aware UTC `datetime`. Only where that UTC value comes from,
# on this one provider path, changes.
#
# This module is the ONLY place in the codebase permitted to express
# the 5h30m constant for this purpose - never inline a
# `timedelta(hours=5, minutes=30)` at a call site.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

IST_UTC_OFFSET = timedelta(hours=5, minutes=30)
"""The Asia/Kolkata (IST) offset from UTC. India does not observe
daylight saving time, so this offset is constant year-round - a fixed
`timedelta` is correct here and a full tz database lookup would add a
dependency without changing any result."""

DHAN_WEBSOCKET_TIMESTAMP_NORMALIZATION_NOTE = (
    "Dhan live-feed WebSocket LTT epoch is IST-labelled; normalized to UTC by "
    "subtracting the fixed 5h30m IST offset (Checkpoint 64.71, evidenced by 2,154 "
    "real observations from the 64.70 live session)."
)
"""A single, reusable, human-readable explanation for logs, docs, and
diagnostics - so the reason for the correction never has to be
re-derived or re-worded (and so it cannot drift out of sync between
several hand-written copies)."""


def normalize_dhan_websocket_timestamp(ltt_epoch: int | float) -> datetime:
    """Converts ONE raw Dhan WebSocket last-trade-time epoch value into
    a correct, timezone-aware UTC `datetime`.

    Dhan's WebSocket LTT field is an epoch-seconds integer whose value
    corresponds to the IST WALL-CLOCK reading rather than to true UTC
    (see this module's docstring for the 2,154-sample evidence). The
    correction is therefore:

        timestamp_utc = epoch_interpreted_as_utc - 5h30m

    Returns a `datetime` that is ALWAYS timezone-aware with `tzinfo` set
    to UTC - the exact contract the canonical `Quote.timestamp` has
    always required, unchanged by this checkpoint.
    """
    return datetime.fromtimestamp(ltt_epoch, tz=UTC) - IST_UTC_OFFSET


__all__ = [
    "DHAN_WEBSOCKET_TIMESTAMP_NORMALIZATION_NOTE",
    "IST_UTC_OFFSET",
    "normalize_dhan_websocket_timestamp",
]
