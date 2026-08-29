# File: src/intraday/signal_intelligence/feature_engine/market_regime.py
#
# Checkpoint 65.08: `market_regime` - the first PRODUCTION categorical
# Market Context feature, built on the `CategoricalFeatureValue`/
# `FieldDataType.CATEGORICAL`/`AnyFeatureValue` seam Checkpoint 65.07
# established (and deliberately did NOT implement `market_regime`
# itself). This module implements exactly the rule Checkpoint 65.06
# already designed (see docs/research/MARKET_CONTEXT_INTELLIGENCE.md
# section 7&8) - it does NOT redesign, tune, or optimize that rule.
#
# `market_regime` is upstream MARKET CONTEXT, never a strategy, never a
# BUY/SELL/HOLD signal, never Gainz-specific, never performance-validated.
#
# ---------------------------------------------------------------------------
# STATE VOCABULARY (closed, enforced here - NOT in CategoricalFeatureValue)
# ---------------------------------------------------------------------------
#
# Exactly four states: BULL, BEAR, SIDEWAYS, TRANSITION. No
# HIGH_VOLATILITY/CRASH/RECOVERY/PANIC/RISK_ON/RISK_OFF, no Fire Sale, no
# "Firecell" (that term was a placeholder used in earlier checkpoints -
# 65.08 corrects it: the real future concept is "Fire Sale", a SEPARATE,
# NOT-implemented concept - see MARKET_CONTEXT_INTELLIGENCE.md section 5).
# `CategoricalFeatureValue` itself remains fully generic (Part B) - this
# module is the ONLY place the BULL/BEAR/SIDEWAYS/TRANSITION vocabulary is
# enforced, via `_REGIME_VOCABULARY` below.
#
# ---------------------------------------------------------------------------
# BASELINE RULE (verbatim from the 65.06 design - not re-derived here)
# ---------------------------------------------------------------------------
#
#     trend_strength_ok = adx_14[t] >= ADX_MIN
#     bull_direction = plus_di_14[t] > minus_di_14[t] AND ema_fast[t] > ema_slow[t]
#     bear_direction = minus_di_14[t] > plus_di_14[t] AND ema_fast[t] < ema_slow[t]
#
#     BULL       if trend_strength_ok AND bull_direction
#     BEAR       if trend_strength_ok AND bear_direction
#     SIDEWAYS   if NOT trend_strength_ok
#     TRANSITION otherwise (trend_strength_ok True, but neither bull_direction
#                nor bear_direction holds - e.g. +DI/-DI and EMA fast/slow
#                ordering disagree, or +DI == -DI, or ema_fast == ema_slow)
#
# `ADX_MIN` is a RESEARCH DEFAULT parameter supplied by the caller via
# `MarketRegimeDefinition.adx_min` - never auto-applied, never optimized
# against any backtest/performance data by this module. 20 is NOT claimed
# to be objectively correct anywhere in this codebase.
#
# ---------------------------------------------------------------------------
# INPUTS - canonical only, fixed ADX/DI period
# ---------------------------------------------------------------------------
#
# Exactly five canonical dependency series, each computed via the SAME
# already-existing public compute functions the dispatcher already calls
# for those fields individually - no second indicator engine, no
# reimplemented math:
#   - adx_14, plus_di_14, minus_di_14: `DirectionalMovementDefinition(14)`
#     via `directional_movement.py`. The DI/ADX smoothing period is FIXED
#     at the canonical 14 - it is NOT one of `MarketRegimeDefinition`'s own
#     parameters (only ADX_MIN, the THRESHOLD compared against adx_14's
#     value, is a market_regime parameter).
#   - ema_fast / ema_slow: `ExponentialMovingAverageDefinition(lookback)`
#     via `ema.py`, at the two lookbacks `MarketRegimeDefinition` carries.
#
# No sector/index/breadth/sentiment/OI data. No Gainz output. No
# EMA-crossover/SMA-trend-filter/ATR-breakout STRATEGY signal.
#
# ---------------------------------------------------------------------------
# PARAMETERIZATION (Part G)
# ---------------------------------------------------------------------------
#
# `MarketRegimeDefinition(adx_min, ema_fast_lookback, ema_slow_lookback)` in
# `definitions.py`. No defaults baked in - every caller supplies all three
# explicitly (matching `ReboundCandidateDefinition`'s own precedent).
# Validated: `adx_min` a positive int, `ema_fast_lookback` a positive int,
# `ema_slow_lookback` a positive int strictly greater than
# `ema_fast_lookback`. Invalid inputs raise `InvalidLookbackError` - NEVER
# silently repaired/swapped/clamped.
#
# ---------------------------------------------------------------------------
# WARM-UP (Part H)
# ---------------------------------------------------------------------------
#
# `market_regime(t)` can only be emitted at a timestamp where ALL FIVE
# dependencies already have a value:
#   - adx_14 needs 2*14 = 28 bars (the latest-binding dependency, per
#     `directional_movement.py`'s own `_compute_directional_series` seed
#     logic: DI/DX need `lookback + 1` bars, and ADX additionally needs
#     `lookback` DX observations to seed its own Wilder average);
#   - plus_di_14 / minus_di_14 need 14 + 1 = 15 bars each;
#   - ema_fast / ema_slow need `ema_fast_lookback` / `ema_slow_lookback`
#     bars respectively (per `ema.py`).
# The feature's own effective warm-up is therefore
# `max(28, ema_slow_lookback)` bars - purely DERIVED from the dependencies'
# own warm-ups (the join below is what actually enforces this - no warm-up
# number is separately invented or hard-coded as a skip-count).
#
# ---------------------------------------------------------------------------
# UNAVAILABLE SEMANTICS (Part I)
# ---------------------------------------------------------------------------
#
# If ANY of the five dependencies lacks a value at a given bar's timestamp,
# that bar produces NO `market_regime` output at all - never a fabricated
# SIDEWAYS or TRANSITION fallback. Missing data is not a business state.
#
# ---------------------------------------------------------------------------
# NO-LOOKAHEAD (Part J)
# ---------------------------------------------------------------------------
#
# `market_regime(t)` reads only the value each dependency produced AT
# timestamp t - each dependency is independently already proven
# (Checkpoints 16/64.49) to depend only on bars at or before t. No future
# bar, no future dependency value, and no t+1 lookup participates in this
# module's join/rule logic.
#
# ---------------------------------------------------------------------------
# DETERMINISM (Part K)
# ---------------------------------------------------------------------------
#
# Pure functions over an immutable `tuple[Bar, ...]` input and a frozen
# `MarketRegimeDefinition` - no mutable module-level state, no persisted
# state, no randomness. Identical input + config always produces identical
# output (categories, timestamps, ordering).
#
# ---------------------------------------------------------------------------
# EDGE CASES (Part M) - explicitly documented branch handling
# ---------------------------------------------------------------------------
#
#   - adx_14[t] == ADX_MIN exactly: `trend_strength_ok` uses `>=`, so this
#     counts as trend-strength-OK (matches direction branch, never SIDEWAYS
#     purely from equality).
#   - plus_di_14[t] == minus_di_14[t]: neither `bull_direction` nor
#     `bear_direction` can be true (both require a strict `>`/`<`) -> if
#     `trend_strength_ok`, result is TRANSITION.
#   - ema_fast[t] == ema_slow[t]: same effect - neither direction condition
#     can hold -> TRANSITION if trend_strength_ok, else SIDEWAYS.
#   - insufficient history / missing adx / missing DI / missing EMA: no
#     output at that timestamp (Part I above) - never a fabricated state.
#   - invalid MarketRegimeDefinition parameters: raises `InvalidLookbackError`
#     at construction time, before any bar is processed.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import CategoricalFeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    DirectionalMovementDefinition,
    ExponentialMovingAverageDefinition,
    MarketRegimeDefinition,
)
from intraday.signal_intelligence.feature_engine.directional_movement import (
    compute_average_directional_index,
    compute_minus_directional_index,
    compute_plus_directional_index,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

# Canonical ADX/+DI/-DI smoothing period - fixed, NOT a MarketRegimeDefinition
# parameter (see module docstring's Inputs section).
CANONICAL_ADX_DI_LOOKBACK = 14

BULL = "BULL"
BEAR = "BEAR"
SIDEWAYS = "SIDEWAYS"
TRANSITION = "TRANSITION"

# Closed vocabulary enforced by THIS module only (Part B) - never widened,
# never used to encode Fire Sale/Firecell/HIGH_VOLATILITY/CRASH/RECOVERY/
# PANIC/RISK_ON/RISK_OFF states.
_REGIME_VOCABULARY = frozenset({BULL, BEAR, SIDEWAYS, TRANSITION})


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


def compute_market_regime(
    definition: MarketRegimeDefinition, bars: tuple[Bar, ...]
) -> tuple[CategoricalFeatureValue, ...]:
    """The single production `market_regime` categorical feature - see
    module docstring for the exact rule, warm-up, unavailable-data,
    no-lookahead, and determinism guarantees.

    Composes FIVE already-existing canonical dependency computations
    (`compute_average_directional_index`, `compute_plus_directional_index`,
    `compute_minus_directional_index`, `compute_exponential_moving_average`
    x2) by timestamp - never recalculates their mathematics."""
    if not bars:
        return ()

    _validate_series(bars)

    instrument_id = bars[0].instrument_id
    timeframe = bars[0].timeframe

    dm_definition = DirectionalMovementDefinition(CANONICAL_ADX_DI_LOOKBACK)
    adx_values = compute_average_directional_index(dm_definition, bars)
    plus_di_values = compute_plus_directional_index(dm_definition, bars)
    minus_di_values = compute_minus_directional_index(dm_definition, bars)
    ema_fast_values = compute_exponential_moving_average(
        ExponentialMovingAverageDefinition(definition.ema_fast_lookback), bars
    )
    ema_slow_values = compute_exponential_moving_average(
        ExponentialMovingAverageDefinition(definition.ema_slow_lookback), bars
    )

    adx_by_ts = {v.timestamp: v.value for v in adx_values}
    plus_di_by_ts = {v.timestamp: v.value for v in plus_di_values}
    minus_di_by_ts = {v.timestamp: v.value for v in minus_di_values}
    ema_fast_by_ts = {v.timestamp: v.value for v in ema_fast_values}
    ema_slow_by_ts = {v.timestamp: v.value for v in ema_slow_values}

    adx_min = Decimal(definition.adx_min)

    values: list[CategoricalFeatureValue] = []
    for bar in bars:
        ts = bar.timestamp
        adx = adx_by_ts.get(ts)
        plus_di = plus_di_by_ts.get(ts)
        minus_di = minus_di_by_ts.get(ts)
        ema_fast = ema_fast_by_ts.get(ts)
        ema_slow = ema_slow_by_ts.get(ts)
        # Honest unavailability (Part I) - if ANY dependency has no value
        # here (warm-up or otherwise), never fabricate a regime state.
        if (
            adx is None
            or plus_di is None
            or minus_di is None
            or ema_fast is None
            or ema_slow is None
        ):
            continue

        trend_strength_ok = adx >= adx_min
        bull_direction = plus_di > minus_di and ema_fast > ema_slow
        bear_direction = minus_di > plus_di and ema_fast < ema_slow

        if trend_strength_ok and bull_direction:
            category = BULL
        elif trend_strength_ok and bear_direction:
            category = BEAR
        elif not trend_strength_ok:
            category = SIDEWAYS
        else:
            category = TRANSITION

        assert category in _REGIME_VOCABULARY  # closed-vocabulary guarantee

        values.append(
            CategoricalFeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=ts,
                category=category,
            )
        )

    return tuple(values)
