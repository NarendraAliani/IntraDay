# File: src/intraday/signal_intelligence/feature_engine/dispatch.py
#
# CHECKPOINT-SCANNER-A: `compute_feature_series` relocated here,
# VERBATIM (a pure move, not a rewrite - every branch, every comment,
# every import it actually uses is unchanged), from
# `application/services/strategy_execution.py`, where it originated
# (Checkpoint 26 Part 15/17 onward) and had lived until now.
#
# WHY THIS LOCATION, not `application/services/feature_computation.py`
# (the roadmap's own first-suggested alternative): `compute_feature_series`
# depends on exactly two things - `intraday.domain.feature.contracts`/
# `intraday.domain.market_data.contracts` (domain - always importable) and
# `intraday.signal_intelligence.feature_engine.*` (itself - already
# importable from inside its own package). It has NEVER depended on
# `intraday.trading_engine.strategy_execution`, `StrategyRegistry`, or
# any other bounded-context type - `strategy_execution.py`'s own module
# comment already documented this precisely ("`compute_feature_series`
# below is the real SMA/EMA/ATR dispatcher INJECTED into
# `StrategyExecutionCoordinator`... This application-layer module is
# exactly where that composition is architecturally permitted" - true
# when it was written, but composition of feature_engine functions BY
# feature_engine itself needs no such permission at all; `.importlinter`
# contract 3/4 only restrict CROSS-bounded-context composition, and this
# function never crosses one). `field_registry.py` (this same package)
# already houses `parse_feature_name()` - the exact parsing algorithm
# this dispatcher's own multi-word-kind branch uses - for the identical
# reason ("LIFTED, not duplicated, so the traceability resolver ... can
# never drift from the dispatcher"). Placing the dispatcher itself here
# too closes that same distance instead of widening it, and lets BOTH
# `application.services.strategy_execution` (existing) and
# `application.services.adhoc_screening` (CHECKPOINT-SCANNER-A, new)
# import it identically - as "application layer importing
# signal_intelligence," exactly what `.importlinter` contract 3 already
# permits either caller to do, with zero new exception and zero new
# application-layer file needed just to hold a pass-through.
#
# `strategy_execution.py` now imports `compute_feature_series` FROM
# here - see that module's own updated header comment.
from __future__ import annotations

from intraday.domain.feature.contracts import AnyFeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.bearish_engulfing import (
    BEARISH_ENGULFING_FIELD_ID,
    compute_bearish_engulfing,
)
from intraday.signal_intelligence.feature_engine.bullish_engulfing import (
    BULLISH_ENGULFING_FIELD_ID,
    compute_bullish_engulfing,
)
from intraday.signal_intelligence.feature_engine.candle_body_ratio import (
    CANDLE_BODY_RATIO_FIELD_ID,
    compute_candle_body_ratio,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    DirectionalMovementDefinition,
    ExponentialMovingAverageDefinition,
    MacdHistogramDefinition,
    MaDivergenceEmaDefinition,
    MaDivergenceSmaDefinition,
    MarketRegimeDefinition,
    OpeningRangeDefinition,
    PriceDeltaDefinition,
    PriceVsMaPctEmaDefinition,
    PriceVsMaPctSmaDefinition,
    ReboundCandidateDefinition,
    RelativeStrengthIndexDefinition,
    RelativeVolumeDefinition,
    RollingBreakoutDefinition,
    SessionVwapDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.directional_movement import (
    compute_average_directional_index,
    compute_minus_directional_index,
    compute_plus_directional_index,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.field_registry import parse_feature_name
from intraday.signal_intelligence.feature_engine.macd_histogram import compute_macd_histogram
from intraday.signal_intelligence.feature_engine.ma_divergence import (
    compute_ma_divergence_ema,
    compute_ma_divergence_sma,
)
from intraday.signal_intelligence.feature_engine.market_regime import compute_market_regime
from intraday.signal_intelligence.feature_engine.opening_range import (
    compute_opening_range_high,
    compute_opening_range_low,
)
from intraday.signal_intelligence.feature_engine.price_delta import compute_price_delta
from intraday.signal_intelligence.feature_engine.price_vs_ma_pct import (
    compute_price_vs_ma_pct_ema,
    compute_price_vs_ma_pct_sma,
)
from intraday.signal_intelligence.feature_engine.rebound_candidate import (
    compute_rebound_candidate,
)
from intraday.signal_intelligence.feature_engine.relative_volume import compute_relative_volume
from intraday.signal_intelligence.feature_engine.rolling_breakout import (
    compute_rolling_breakout,
)
from intraday.signal_intelligence.feature_engine.rsi import compute_relative_strength_index
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average
from intraday.signal_intelligence.feature_engine.vwap import compute_session_vwap


def compute_feature_series(field_id: str, bars: tuple[Bar, ...]) -> tuple[AnyFeatureValue, ...]:
    """Dispatches one "sma_20"/"ema_9"/"atr_14"/"rsi_14"/"adx_14"/
    "plus_di_14"/"minus_di_14"/"relative_volume_20"/
    "macd_hist_12_26_9"/"candle_body_ratio"/"market_regime_20_9_20"/
    "rolling_breakout_20"-shaped field_id to the matching existing
    compute function. Raises ValueError
    for anything else - callers only ever pass field_ids strategies
    themselves declared via `required_features()` (raw OHLCV fields are
    read straight off `Bar`, never computed).

    Checkpoint 64.49 adds RSI/ADX/+DI/-DI/Relative Volume/MACD Histogram/
    Candle Body Ratio dispatch, following the exact same parse-then-
    construct-a-Definition-then-call-the-pure-function shape SMA/EMA/ATR
    already established - no second dispatch mechanism introduced.

    Checkpoint 65.08: return type widened from `tuple[FeatureValue, ...]`
    to `tuple[AnyFeatureValue, ...]` (a minimal, generic typing correction
    - the union type itself was already introduced by 65.07 for exactly
    this seam) so the new `market_regime` branch can return
    `tuple[CategoricalFeatureValue, ...]`. Every existing numeric branch
    below is completely unchanged - each still returns its own
    `tuple[FeatureValue, ...]`, which `AnyFeatureValue` accepts without
    any behavioural change.

    CHECKPOINT-SCANNER-A: relocated here verbatim from
    `application.services.strategy_execution` - see this module's own
    header comment for why. No behavioural change; every branch below is
    byte-identical to the version that lived in `strategy_execution.py`."""
    if field_id == CANDLE_BODY_RATIO_FIELD_ID:
        return compute_candle_body_ratio(bars)
    if field_id == BULLISH_ENGULFING_FIELD_ID:
        return compute_bullish_engulfing(bars)
    if field_id == BEARISH_ENGULFING_FIELD_ID:
        return compute_bearish_engulfing(bars)

    # Multi-word kinds ("plus_di", "minus_di", "relative_volume",
    # "macd_hist") need the SUFFIX of trailing integer parameters
    # stripped, not just a single first-`_`-partition - unlike
    # "sma_20"/"ema_9"/"atr_14"/"rsi_14"/"adx_14", which are already a
    # single-word kind.
    # Checkpoint 64.81: the parse itself now lives in
    # `feature_engine.field_registry.parse_feature_name()` - LIFTED, not
    # duplicated, so the traceability resolver that maps a feature name
    # back to its canonical registry field_id can never drift from this
    # dispatcher. The algorithm is byte-for-byte the one this function
    # has used since Checkpoint 64.49; no dispatch behaviour changes.
    kind, params = parse_feature_name(field_id)

    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(params[0]), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(params[0]), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(params[0]), bars)
    if kind == "rsi":
        return compute_relative_strength_index(RelativeStrengthIndexDefinition(params[0]), bars)
    if kind == "adx":
        return compute_average_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "plus_di":
        return compute_plus_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "minus_di":
        return compute_minus_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "relative_volume":
        return compute_relative_volume(RelativeVolumeDefinition(params[0]), bars)
    if kind == "macd_hist":
        return compute_macd_histogram(MacdHistogramDefinition(*params), bars)
    if kind == "price_delta":
        return compute_price_delta(PriceDeltaDefinition(params[0]), bars)
    if kind == "price_vs_ma_pct_sma":
        return compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(params[0]), bars)
    if kind == "price_vs_ma_pct_ema":
        return compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(params[0]), bars)
    if kind == "rebound_candidate":
        return compute_rebound_candidate(ReboundCandidateDefinition(*params), bars)
    if kind == "ma_divergence_sma":
        return compute_ma_divergence_sma(MaDivergenceSmaDefinition(*params), bars)
    if kind == "ma_divergence_ema":
        return compute_ma_divergence_ema(MaDivergenceEmaDefinition(*params), bars)
    if kind == "market_regime":
        return compute_market_regime(MarketRegimeDefinition(*params), bars)
    if kind == "rolling_breakout":
        return compute_rolling_breakout(RollingBreakoutDefinition(*params), bars)
    if kind == "vwap":
        return compute_session_vwap(SessionVwapDefinition(*params), bars)
    if kind == "opening_range_high":
        return compute_opening_range_high(OpeningRangeDefinition(*params), bars)
    if kind == "opening_range_low":
        return compute_opening_range_low(OpeningRangeDefinition(*params), bars)
    raise ValueError(f"unrecognized computed field_id {field_id!r}")


__all__ = ["compute_feature_series"]
