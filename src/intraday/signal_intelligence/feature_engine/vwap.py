# File: src/intraday/signal_intelligence/feature_engine/vwap.py
#
# CHECKPOINT-VWAP-A: Session-Anchored VWAP - a canonical, reusable
# PLATFORM feature, Phase A of `VWAP_STRATEGY_ROADMAP.md`. Standard,
# well-established technical-analysis convention (typical-price,
# volume-weighted, reset at each session boundary) - not a Gainz port,
# not verified against any external reference (this is a genuinely new
# strategy thread, unrelated to `gainz_compatible_research.py`, which
# remains paused per `CHECKPOINT_75`'s explicit resumption criterion and
# is not touched by this checkpoint).
#
# ---------------------------------------------------------------------------
# FORMULA - explicit
# ---------------------------------------------------------------------------
#
#     typical_price_t = (high_t + low_t + close_t) / 3
#
#     vwap_t = Σ(typical_price_i * volume_i) / Σ(volume_i)
#              for i = (first bar of t's trading day) .. t
#
# The standard, textbook VWAP definition (typical price, not close alone
# - close-only would be a DIFFERENT, non-standard indicator and is
# deliberately not what this module computes).
#
# ---------------------------------------------------------------------------
# Session-reset accumulator - THE genuinely new computation shape this
# feature requires (see `VWAP_STRATEGY_ROADMAP.md` §1.2's own recon
# finding: no existing feature-engine module has any session-boundary
# concept - every other feature uses a FIXED trailing `deque(maxlen=N)`
# window that has no concept of "reset"). Reuses the exact grouping
# primitive `research/backtesting/walk_forward.py` already established
# and proved (`bar.timestamp.date()`, UTC - see that module's own
# `bars_by_date` dict, `walk_forward.py:128-130`), not a new, unproven
# idea: whenever the CURRENT bar's `.timestamp.date()` differs from the
# PREVIOUS bar's, the running numerator/denominator accumulators reset
# to zero before this bar is included. `Bar.timestamp` is UTC bar CLOSE
# time (`domain/market_data/contracts.py`), and NSE/BSE cash-equity
# trading hours (09:15-15:30 IST = 03:45-10:00 UTC) never cross a UTC
# midnight boundary for any real session this platform handles - so
# `.date()` grouping in UTC is sufficient on its own; no IST conversion
# and no separate session marker on `Bar` is needed
# (`VWAP_STRATEGY_ROADMAP.md` §1.3's own confirmed reasoning, re-used
# here, not re-derived).
#
# ---------------------------------------------------------------------------
# Warm-up - NONE, unlike every lookback-based feature in this package
# ---------------------------------------------------------------------------
#
# Unlike SMA/EMA/ATR/RSI/ADX/Relative-Volume/Rolling-Breakout (all of
# which require N prior bars before their first output), VWAP can
# produce a value starting from the VERY FIRST bar of each trading day -
# a session of one single bar already has a well-defined VWAP (that
# bar's own typical price). The only condition under which a bar
# produces NO value is a zero-cumulative-volume denominator (every bar
# in the session so far, including this one, had zero volume) - that
# specific bar is SKIPPED entirely, mirroring `candle_body_ratio.py`'s
# own "mathematically undefined - skip, never fabricate a value"
# precedent for its own zero-range-bar edge case, never a
# division-by-zero crash and never a fabricated 0.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    SessionVwapDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

_THREE = Decimal(3)


def compute_session_vwap(
    definition: SessionVwapDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """Session-anchored Volume-Weighted Average Price (see module
    docstring for the full formula, session-reset mechanism, and
    warm-up rationale).

    No look-ahead: `vwap_t` is a running cumulative sum over bars
    `0..t` WITHIN the current trading day only - a later bar (whether
    later the same day or on a future day) can never influence an
    earlier bar's output, since the accumulators are only ever added
    to going forward, never revisited or recomputed once emitted.
    `definition` carries no tunable parameter (see
    `SessionVwapDefinition`'s own docstring for why it still exists) -
    accepted only for the same parse-then-construct-a-Definition-then-
    call-the-pure-function shape every other derived feature in this
    package follows.
    """
    if not bars:
        return ()

    ensure_chronological(bars)

    instrument_id = bars[0].instrument_id
    timeframe = bars[0].timeframe
    for bar in bars:
        if bar.instrument_id != instrument_id:
            raise MixedInstrumentSeriesError(
                f"bar series mixes instruments {instrument_id!r} and "
                f"{bar.instrument_id!r} - a feature series must come from one instrument"
            )
        if bar.timeframe != timeframe:
            raise MixedTimeframeSeriesError(
                f"bar series mixes timeframes {timeframe!r} and {bar.timeframe!r} "
                "- a feature calculation must never blend timeframes"
            )

    values: list[FeatureValue] = []
    current_session_date = None
    cumulative_price_volume = Decimal(0)
    cumulative_volume = Decimal(0)

    for bar in bars:
        bar_date = bar.timestamp.date()
        if bar_date != current_session_date:
            # New trading day (or the very first bar) - reset BEFORE
            # this bar is included, so day 2 never inherits day 1's
            # accumulators.
            current_session_date = bar_date
            cumulative_price_volume = Decimal(0)
            cumulative_volume = Decimal(0)

        typical_price = (bar.high + bar.low + bar.close) / _THREE
        cumulative_price_volume += typical_price * bar.volume
        cumulative_volume += bar.volume

        if cumulative_volume == 0:
            # Every bar in this session so far (including this one) had
            # zero volume - VWAP is mathematically undefined. Skip, per
            # `candle_body_ratio.py`'s own precedent - never a fabricated
            # value, never a division-by-zero crash.
            continue

        vwap_value = cumulative_price_volume / cumulative_volume
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=vwap_value,
            )
        )

    return tuple(values)
