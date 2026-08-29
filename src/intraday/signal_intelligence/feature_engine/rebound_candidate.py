# File: src/intraday/signal_intelligence/feature_engine/rebound_candidate.py
#
# Checkpoint 65.04: Short-Term Rebound Candidate - a generic, deterministic
# MARKET CONTEXT feature. This is NOT a strategy, NOT a BUY/SELL/HOLD
# signal, NOT a target/stop-loss/entry, NOT Gainz-specific, and NOT
# performance-validated. It answers exactly one question: "does current
# price action exhibit a deterministic short-term rebound SETUP?" - the
# Strategy layer (a future checkpoint, out of scope here) decides what, if
# anything, to do with that context. See
# `docs/research/MARKET_CONTEXT_INTELLIGENCE.md`'s Short-Term Rebound
# section for the research-level writeup this module implements.
#
# ---------------------------------------------------------------------------
# PART A/B - rule design, decided BEFORE writing this function
# ---------------------------------------------------------------------------
#
# Candidate ingredients considered (per the checkpoint directive): recent
# negative price delta, oversold RSI, bullish reversal evidence, volume
# confirmation, price below/near a moving average. This module does NOT
# use all of them - only the smallest coherent subset that together
# express "a decline occurred, then a reversal signature appeared":
#
#   INCLUDED:
#     1. price_delta_N(t) < 0   - a decline actually happened over the
#        last N bars (the thing being "rebounded" from). Without this,
#        "rebound" has no antecedent to rebound FROM.
#     2. rsi_M(t) < oversold_threshold - the decline pushed momentum into
#        an oversold state (a generic, already-canonical way to express
#        "the decline was significant enough to matter", not just any
#        negative delta).
#     3. bullish_engulfing(t) == 1 - a concrete, already-canonical
#        reversal CANDLE exists at t itself (not merely "no longer
#        falling" - an actual bullish reversal pattern printed).
#
#   DELIBERATELY EXCLUDED:
#     - relative_volume (volume confirmation): excluded because it adds a
#       FOURTH parameter to a concept that is already fully expressible
#       with the three above, and because this platform's own
#       `relative_volume`/`volume` field docs note SAMPLE_BAR-sourced
#       fixtures always carry `volume == 0` - requiring it here would make
#       the feature spuriously unavailable across most of this platform's
#       current fixture/historical data, for no corresponding gain in
#       what the CONTEXT concept itself needs to express. A future
#       strategy that wants volume-confirmed rebounds can already combine
#       `rebound_candidate` with `relative_volume` itself - that
#       composition belongs at the STRATEGY layer, not baked into this
#       context feature.
#     - price_vs_ma_pct (price below/near a moving average): excluded as
#       REDUNDANT with the two included momentum/decline conditions - a
#       bar satisfying "N-bar decline" AND "oversold RSI" is already, in
#       virtually every real case, also below its own short/medium MA;
#       adding a fourth condition and parameter to re-assert the same
#       fact would not sharpen the concept, only fragment it into more
#       parameters that were never independently justified. Left for a
#       future strategy to layer on if a real consumer needs it.
#
# This keeps the feature MINIMALLY parameterized (three numeric
# parameters: `delta_lookback`, `rsi_lookback`, `rsi_oversold_threshold`)
# while remaining a coherent, generic, composable CONTEXT feature - never
# a Gainz-weighted score, never an optimized threshold search result.
#
#     rebound_candidate(t) = 1  if  price_delta_N(t) < 0
#                             AND  rsi_M(t) < rsi_oversold_threshold
#                             AND  bullish_engulfing(t) == 1
#                         = 0  otherwise (all three dependencies available
#                             at t, but the combined condition is false)
#                         = UNAVAILABLE (no output at t) if ANY dependency
#                             has no value at t (warm-up or otherwise)
#
# ---------------------------------------------------------------------------
# PART D - parameterization
# ---------------------------------------------------------------------------
#
# `ReboundCandidateDefinition(delta_lookback, rsi_lookback,
# rsi_oversold_threshold)` in `definitions.py`. No default values are
# baked into the definition itself - exactly like `PriceDeltaDefinition`,
# every caller supplies all three explicitly. The values below are
# published ONLY as RESEARCH DEFAULTS (never auto-applied, never used by
# any production call site this checkpoint):
#
#   RESEARCH_DEFAULT_DELTA_LOOKBACK = 10   (mirrors price_delta.py's own
#       REFERENCE_ARTIFACT_DEFAULT_LOOKBACK - a documented convenience,
#       not a validated market parameter)
#   RESEARCH_DEFAULT_RSI_LOOKBACK = 14     (the standard Wilder RSI period
#       convention rsi.py's own docstring already documents as the
#       "market default" - a well-known TA convention, not tuned here)
#   RESEARCH_DEFAULT_RSI_OVERSOLD_THRESHOLD = 30  (the classic textbook
#       RSI oversold line - a well-known TA convention, NOT threshold-
#       optimized against any performance data by this checkpoint)
#
# These are documentation-only constants (identical provenance discipline
# to `price_delta.REFERENCE_ARTIFACT_DEFAULT_LOOKBACK`) - reclassify as a
# VALIDATED MARKET PARAMETER only if a future checkpoint actually
# validates them against real outcome data.
#
# ---------------------------------------------------------------------------
# PART E/L - dependency composition, no duplicated math, no N+1 recompute
# ---------------------------------------------------------------------------
#
# All three dependency series are computed ONCE each (`compute_price_delta`,
# `compute_relative_strength_index`, `compute_bullish_engulfing` - the
# exact same public functions the dispatcher already calls for those
# fields individually), then joined by timestamp. No private indicator
# math is reimplemented or duplicated anywhere in this module.
#
# ---------------------------------------------------------------------------
# PART G - warm-up
# ---------------------------------------------------------------------------
#
# No second warm-up convention is invented. `rebound_candidate(t)` can
# only ever be emitted at a timestamp where ALL THREE dependencies already
# have a value:
#   - price_delta_N needs N+1 bars before its first output;
#   - rsi_M needs M+1 bars before its first output;
#   - bullish_engulfing needs 2 bars before its first output.
# The feature's own effective warm-up is therefore
# `max(delta_lookback, rsi_lookback) + 1` bars (whichever dependency's
# own warm-up is the LATEST determines the first possible output) -
# purely DERIVED from the three dependencies' own warm-ups, never a
# separately chosen number.
#
# ---------------------------------------------------------------------------
# PART F - no-lookahead
# ---------------------------------------------------------------------------
#
# `rebound_candidate(t)` reads only the value each dependency produced AT
# timestamp t - and each dependency (`price_delta`, `rsi`,
# `bullish_engulfing`) is independently already proven to depend only on
# bars at or before t. No future bar, no future dependency value, and no
# t+1 lookup ever participates in this function's own join/compare logic.
#
# ---------------------------------------------------------------------------
# PART H - honest unavailability
# ---------------------------------------------------------------------------
#
# If ANY dependency lacks a value at a given bar's timestamp (insufficient
# history, or - in principle - a dependency's own internal skip, e.g.
# `price_vs_ma_pct`'s zero-MA skip pattern; none of the three dependencies
# used here has such a skip case today, but the join logic below handles
# it generically regardless), that bar produces NO `rebound_candidate`
# output at all - never a fabricated 0/1.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.bullish_engulfing import (
    compute_bullish_engulfing,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    ReboundCandidateDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.price_delta import compute_price_delta
from intraday.signal_intelligence.feature_engine.rsi import compute_relative_strength_index

# RESEARCH DEFAULTS ONLY - see module docstring's Part D section. Never
# auto-applied anywhere; every `ReboundCandidateDefinition` construction
# requires all three parameters explicitly.
RESEARCH_DEFAULT_DELTA_LOOKBACK = 10
RESEARCH_DEFAULT_RSI_LOOKBACK = 14
RESEARCH_DEFAULT_RSI_OVERSOLD_THRESHOLD = 30

_ZERO = Decimal(0)
_ONE = Decimal(1)


def compute_rebound_candidate(
    definition: ReboundCandidateDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """Generic short-term rebound-candidate context feature - see module
    docstring for the exact rule, its inclusion/exclusion rationale, and
    the warm-up/no-lookahead/honest-unavailability guarantees.

    Composes THREE already-existing canonical feature computations
    (`compute_price_delta`, `compute_relative_strength_index`,
    `compute_bullish_engulfing`) by timestamp - never recalculates their
    mathematics."""
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

    delta_values = compute_price_delta(definition.price_delta_definition, bars)
    rsi_values = compute_relative_strength_index(definition.rsi_definition, bars)
    engulfing_values = compute_bullish_engulfing(bars)

    delta_by_ts = {v.timestamp: v.value for v in delta_values}
    rsi_by_ts = {v.timestamp: v.value for v in rsi_values}
    engulfing_by_ts = {v.timestamp: v.value for v in engulfing_values}

    threshold = Decimal(definition.rsi_oversold_threshold)

    values: list[FeatureValue] = []
    for bar in bars:
        delta = delta_by_ts.get(bar.timestamp)
        rsi = rsi_by_ts.get(bar.timestamp)
        engulfing = engulfing_by_ts.get(bar.timestamp)
        # Honest unavailability - if ANY dependency has no value here
        # (warm-up or otherwise), never fabricate a rebound state.
        if delta is None or rsi is None or engulfing is None:
            continue
        is_rebound = delta < _ZERO and rsi < threshold and engulfing == _ONE
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=_ONE if is_rebound else _ZERO,
            )
        )

    return tuple(values)
