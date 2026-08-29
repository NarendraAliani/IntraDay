# File: src/intraday/signal_intelligence/feature_engine/ma_divergence.py
#
# Checkpoint 65.05: Moving Average Divergence - a generic, deterministic
# MARKET CONTEXT feature. This is NOT a trading signal, NOT a crossover
# EVENT, NOT BUY/SELL/HOLD, NOT Gainz-specific, and NOT performance-
# validated. It answers exactly one numeric question: "how far apart, as
# a fraction of the slow MA, are a fast moving average and a slow moving
# average right now?" - a future strategy/context layer can derive a
# crossing EVENT by comparing `ma_divergence[t]` against
# `ma_divergence[t-1]` itself; that layer is explicitly OUT OF SCOPE here
# (see docs/research/MARKET_CONTEXT_INTELLIGENCE.md's Moving Average
# Diversions section).
#
#     ma_divergence(t) = (fast_ma(t) - slow_ma(t)) / slow_ma(t)
#
# Output is a SIGNED Decimal fraction (NOT pre-multiplied by 100 -
# identical convention to `price_vs_ma_pct`, which is also a bare
# ratio). >0 means the fast MA is above the slow MA, <0 means the fast MA
# is below the slow MA, =0 means they are exactly equal. NEVER a boolean,
# NEVER a crossover-state enum.
#
# ---------------------------------------------------------------------------
# PART A - MA-type-combination support decision (made BEFORE coding)
# ---------------------------------------------------------------------------
#
# The directive asks which of {SMA fast + SMA slow, EMA fast + EMA slow,
# SMA fast + EMA slow, EMA fast + SMA slow} the architecture should
# support. Inspecting `field_registry.parse_feature_name()` (the exact
# algorithm both `field_registry.resolve_feature_name()` and
# `application.services.strategy_execution.compute_feature_series()`'s
# dispatcher use) confirms - exactly as 65.03's `price_vs_ma_pct` module
# already documented - that it only strips a TRAILING RUN OF INTEGER
# segments off a feature name. MA type ("sma"/"ema") is categorical, not
# numeric, so (again, exactly like 65.03) it cannot be smuggled into that
# trailing-integer slot; it must be folded into the KIND instead.
#
# `ma_divergence` needs to express TWO MA-type slots (fast, slow), not
# one. Naively that is 2x2 = 4 combinations. This module implements only
# the two SAME-TYPE combinations - `ma_divergence_sma` (SMA fast + SMA
# slow) and `ma_divergence_ema` (EMA fast + EMA slow) - and deliberately
# does NOT add `ma_divergence_sma_ema`/`ma_divergence_ema_sma` mixed-type
# identities this checkpoint, because:
#
#   1. Every real-world "moving average divergence" convention this
#      platform's own prior checkpoints have referenced (65.02's audit
#      doc, `ema_crossover`'s own strategy definition, textbook MACD-style
#      fast/slow constructs) compares two MAs of the SAME type - nothing
#      in this codebase or its research docs establishes a canonical,
#      non-arbitrary definition of what a MIXED SMA/EMA divergence would
#      even mean or when a trader would reach for one over the matched-
#      type version.
#   2. The directive itself gates mixed types behind "only if justified" -
#      absent an existing canonical precedent (unlike SMA-vs-SMA and
#      EMA-vs-EMA, which mirror `price_vs_ma_pct_sma`/`_ema`'s own
#      already-accepted precedent exactly), adding two more identities
#      would be speculative surface area, not a reuse of an established
#      pattern.
#   3. The SAME-TYPE identities alone already cover the two most common
#      documented use cases (fast/slow SMA pair, fast/slow EMA pair,
#      matching the classic 9/20, 20/50, 50/200-style period pairs some
#      of which are explicitly NOT hard-coded here - see Part C) without
#      any loss of the CORE numeric semantic the directive asks for.
#
# This is the smallest architecture-compatible representation: TWO field
# identities (matching `price_vs_ma_pct`'s own precedent count exactly),
# each taking two numeric parameters (`fast_lookback`, `slow_lookback`),
# both delegating to the SAME canonical SMA/EMA compute functions - no
# second moving-average engine, no third parsing convention.
#
# ---------------------------------------------------------------------------
# PART B - not a crossover
# ---------------------------------------------------------------------------
#
# This module outputs ONLY the signed numeric ratio above. It does not
# compute, store, or expose `bullish_cross`/`bearish_cross`/
# `crossover_state`, and it must never be confused with the existing
# `ema_crossover` STRATEGY (trading_engine layer) - this is a
# feature-engine MARKET CONTEXT computation with no BUY/SELL/HOLD
# decision attached. A future strategy/context layer can trivially derive
# a crossing by comparing two adjacent `ma_divergence` values' signs -
# that derivation is explicitly not built here.
#
# ---------------------------------------------------------------------------
# PART C - parameterization
# ---------------------------------------------------------------------------
#
# `MaDivergenceSmaDefinition(fast_lookback, slow_lookback)` /
# `MaDivergenceEmaDefinition(fast_lookback, slow_lookback)` in
# `definitions.py`. No defaults are baked into either definition - every
# caller supplies both explicitly (exactly like `MacdHistogramDefinition`/
# `PriceDeltaDefinition`/`ReboundCandidateDefinition`). `__post_init__`
# validates both are positive integers AND `fast_lookback <
# slow_lookback` - an invalid combination raises `InvalidLookbackError`;
# fast/slow are NEVER silently swapped.
#
# The classic period pairs sometimes associated with "moving average
# divergence" (9/20, 20/50, 50/200) are NOT hard-coded or defaulted
# anywhere in this module - they would only ever be RESEARCH DEFAULTS
# (documentation-only, unvalidated against any performance data), and
# this checkpoint does not even publish such constants, unlike
# `rebound_candidate.py`'s RESEARCH_DEFAULT_* constants, because no
# concrete consumer has asked for one yet - adding one speculatively
# would invite exactly the kind of "looks validated" mistake the
# directive explicitly warns against.
#
# ---------------------------------------------------------------------------
# PART D/E/L - canonical MA reuse, warm-up, no duplicated math
# ---------------------------------------------------------------------------
#
# Both the fast and slow MA series are computed ONCE each via the
# existing canonical `compute_simple_moving_average`/
# `compute_exponential_moving_average` public functions (never a private
# indicator function, never reimplemented math), then joined by
# timestamp. `ma_divergence(t)` can only ever be emitted at a timestamp
# where BOTH the fast and slow MA already have a value - the feature's
# own effective warm-up is therefore exactly `slow_lookback` bars (since
# `fast_lookback < slow_lookback` is enforced, the slow MA's own warm-up
# is always the later, binding one) - purely DERIVED from the two MA
# dependencies' own warm-ups, never a separately invented number. No
# second warm-up convention exists in this module.
#
# ---------------------------------------------------------------------------
# PART G - no-lookahead
# ---------------------------------------------------------------------------
#
# `ma_divergence(t)` reads only the fast/slow MA VALUE each already
# produced at timestamp t - and both `compute_simple_moving_average`/
# `compute_exponential_moving_average` are already proven (Checkpoints
# 15/16) to depend only on bars at or before t. No future bar, no future
# MA value, and no t+1 lookup ever participates in this module's join/
# formula logic.
#
# ---------------------------------------------------------------------------
# PART F - zero/invalid slow MA
# ---------------------------------------------------------------------------
#
# If `slow_ma(t) == 0`, this module SKIPS that output entirely - the same
# "skip, never fabricate" discipline `price_vs_ma_pct.py` already
# established for its own zero-MA case (and `candle_body_ratio.py`/
# `relative_volume.py` established for their own zero-denominator cases).
# NEVER a raw `ZeroDivisionError`, NEVER a fabricated `inf`/`0`/`None`
# stand-in value.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    MaDivergenceEmaDefinition,
    MaDivergenceSmaDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average


def _validate_series(bars: tuple[Bar, ...]) -> None:
    """Series-integrity checks identical to every other feature in this
    engine - reused via `ensure_chronological`, not reimplemented."""
    if not bars:
        return
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


def _ma_divergence_from_ma_series(
    feature_name: str,
    feature_version,
    instrument_id,
    timeframe,
    fast_ma_values: tuple[FeatureValue, ...],
    slow_ma_values: tuple[FeatureValue, ...],
) -> tuple[FeatureValue, ...]:
    """Shared core: joins two already-computed MA `FeatureValue` series
    (fast, slow - this function does not know or care whether they are
    SMA or EMA) by timestamp into signed `ma_divergence` values. A zero
    slow-MA value is skipped (see module docstring's Part F), never
    dividing by zero."""
    slow_by_ts = {v.timestamp: v.value for v in slow_ma_values}
    values: list[FeatureValue] = []
    for fast in fast_ma_values:
        slow = slow_by_ts.get(fast.timestamp)
        if slow is None or slow == 0:
            continue
        values.append(
            FeatureValue(
                feature_name=feature_name,
                feature_version=feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=fast.timestamp,
                value=(fast.value - slow) / slow,
            )
        )
    return tuple(values)


def compute_ma_divergence_sma(
    definition: MaDivergenceSmaDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`ma_divergence` between two canonical SMAs - see module docstring
    for the full formula/warm-up/look-ahead/zero-MA/MA-type-support
    documentation."""
    if not bars:
        return ()
    _validate_series(bars)
    fast_values = compute_simple_moving_average(definition.fast_sma_definition, bars)
    slow_values = compute_simple_moving_average(definition.slow_sma_definition, bars)
    return _ma_divergence_from_ma_series(
        definition.feature_name,
        definition.feature_version,
        bars[0].instrument_id,
        bars[0].timeframe,
        fast_values,
        slow_values,
    )


def compute_ma_divergence_ema(
    definition: MaDivergenceEmaDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`ma_divergence` between two canonical EMAs - see module docstring
    for the full formula/warm-up/look-ahead/zero-MA/MA-type-support
    documentation."""
    if not bars:
        return ()
    _validate_series(bars)
    fast_values = compute_exponential_moving_average(definition.fast_ema_definition, bars)
    slow_values = compute_exponential_moving_average(definition.slow_ema_definition, bars)
    return _ma_divergence_from_ma_series(
        definition.feature_name,
        definition.feature_version,
        bars[0].instrument_id,
        bars[0].timeframe,
        fast_values,
        slow_values,
    )
