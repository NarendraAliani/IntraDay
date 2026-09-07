# File: src/intraday/signal_intelligence/feature_engine/rolling_breakout.py
#
# CHECKPOINT-GAINZ-A: Rolling N-Bar Breakout/Breakdown - a canonical,
# reusable PLATFORM feature. Closes BLOCKER A documented in
# `GAINZ_ROADMAP.md` ("20-bar breakout/breakdown - no canonical
# rolling-high/low feature existed at Checkpoint 64.99"). This is a pure
# feature-engine addition only - no strategy logic, no
# `gainz_compatible_research.py` change, no `registry.py` change.
#
# ---------------------------------------------------------------------------
# FORMULA - explicit
# ---------------------------------------------------------------------------
#
#     prior_high_t = max(high_(t-N) .. high_(t-1))   (previous N bars,
#                                                       EXCLUDING the
#                                                       current bar)
#     prior_low_t  = min(low_(t-N) .. low_(t-1))     (previous N bars,
#                                                       EXCLUDING the
#                                                       current bar)
#
#     rolling_breakout_N(t) =  1  if close_t > prior_high_t   (breakout)
#                            = -1  if close_t < prior_low_t   (breakdown)
#                            =  0  otherwise (close stays within the
#                                  prior N-bar high/low range)
#
# The prior-N-bar window is STRICTLY PRIOR to the current bar - the
# current bar's own high/low never participates in its own breakout/
# breakdown test, exactly like `relative_volume.py`'s baseline window
# (see that module's docstring, which this module's warm-up convention
# matches exactly - both use a fixed-size trailing `deque(maxlen=N)`
# that is only APPENDED to the window AFTER the current bar's value is
# computed).
#
# ---------------------------------------------------------------------------
# Representation choice
# ---------------------------------------------------------------------------
#
# No existing canonical feature encodes a THREE-way condition
# (breakout / breakdown / neither) - `bullish_engulfing`/
# `bearish_engulfing` each encode ONE binary condition as Decimal 1/0
# (see `bullish_engulfing.py`'s own "Representation" note: no boolean
# variant of `FeatureValue.value` exists). Rather than split this into
# two separate binary fields (`rolling_breakout`/`rolling_breakdown`,
# mirroring the reference file's two-boolean-column shape rejected by
# `price_delta.py`'s own precedent), this module follows
# `price_delta.py`'s "smallest canonical representation" precedent and
# uses a single SIGNED value: `1` = breakout, `-1` = breakdown, `0` =
# neither. Breakout and breakdown are mutually exclusive by construction
# (a single `close_t` cannot be simultaneously above `prior_high_t` AND
# below `prior_low_t`, since `prior_high_t >= prior_low_t` always), so
# no information is lost collapsing them into one signed field - a
# future consumer recovers "is this a breakout" as `value == 1` and
# "is this a breakdown" as `value == -1`, exactly as `price_delta.py`'s
# sign is recovered as `> 0` / `< 0`.
#
# ---------------------------------------------------------------------------
# Warm-up (matches `relative_volume.py` exactly - see that module's own
# "Warm-up" section, lines 36-44)
# ---------------------------------------------------------------------------
#
# The first `lookback` bars produce NO output (no complete trailing
# prior-N-bar window yet exists) - first possible output at
# `bars[lookback]` (0-indexed). Never a fabricated 0/False before N
# bars exist - an early `close` compared against a partial or empty
# window would not be a real breakout/breakdown test, so no value is
# emitted at all until the window is full, identical in SHAPE to
# `relative_volume.py`'s own warm-up rule (`compute_relative_volume`,
# `relative_volume.py:97-111`).
from __future__ import annotations

from collections import deque
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    RollingBreakoutDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def compute_rolling_breakout(
    definition: RollingBreakoutDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """Rolling N-bar breakout/breakdown (see module docstring for the
    full formula, representation, and warm-up rationale).

    No look-ahead: the prior-N-bar window only ever contains bars
    strictly BEFORE the current bar (a fixed-size trailing `deque`,
    appended to only AFTER the current bar's value is computed) - in
    the chronological order `ensure_chronological()` below already
    guarantees.
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

    lookback = definition.lookback
    high_window: deque[Decimal] = deque(maxlen=lookback)
    low_window: deque[Decimal] = deque(maxlen=lookback)
    values: list[FeatureValue] = []

    for bar in bars:
        if len(high_window) == lookback:
            prior_high = max(high_window)
            prior_low = min(low_window)
            if bar.close > prior_high:
                signal = Decimal(1)
            elif bar.close < prior_low:
                signal = Decimal(-1)
            else:
                signal = Decimal(0)
            values.append(
                FeatureValue(
                    feature_name=definition.feature_name,
                    feature_version=definition.feature_version,
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    timestamp=bar.timestamp,
                    value=signal,
                )
            )
        high_window.append(bar.high)
        low_window.append(bar.low)

    return tuple(values)
