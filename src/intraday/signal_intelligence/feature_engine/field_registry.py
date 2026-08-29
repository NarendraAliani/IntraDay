# File: src/intraday/signal_intelligence/feature_engine/field_registry.py
#
# Checkpoint 26: canonical field/feature registry - the single source of
# truth for "what data fields exist that a strategy could reference",
# consumed by both the dynamic parameter-schema builder
# (`trading_engine/strategy_execution/contracts.py`) and the frontend's
# dependent dropdowns (via the generated API). Deliberately additive:
# does not replace or duplicate `definitions.py`'s existing
# `SimpleMovingAverageDefinition`/`ExponentialMovingAverageDefinition`/
# `AverageTrueRangeDefinition` (those remain the actual computation
# identities `sma.py`/`ema.py`/`atr.py` consume) - this module only
# *describes* the fields those definitions and `domain.market_data.Bar`
# already produce, for selection/validation purposes.
#
# Only fields with a real, tested implementation are listed (raw OHLCV
# from `domain.market_data.contracts.Bar`, plus SMA/EMA/ATR from the
# existing feature engine). No RSI/VWAP/MACD/Bollinger/Supertrend entry
# is fabricated - Checkpoint 26 Part 4 explicitly forbids listing
# indicators that do not exist.
#
# ---------------------------------------------------------------------------
# Checkpoint 64.49 - GAINZ-COMPATIBLE CANONICAL FEATURE EXPANSION
# ---------------------------------------------------------------------------
#
# Checkpoint 64.48 independently re-confirmed (a fourth time, matching
# three prior checkpoints' findings) that NO real Gainz reference source
# file exists anywhere in this repository. 64.49 is therefore NOT a
# Gainz-math port - it is a PLATFORM feature-layer expansion, building
# reusable canonical features using STANDARD, well-established technical-
# analysis conventions (Wilder RSI, Wilder ADX/+DI/-DI, standard 12/26/9
# MACD, etc.) that could serve a future Gainz-like strategy - or any
# strategy - not features reverse-engineered from a Gainz source that
# does not exist.
#
# Added this checkpoint: `rsi`, `adx`, `plus_di`, `minus_di`,
# `relative_volume`, `macd_hist`, `candle_body_ratio` - each backed by a
# real, tested module under `signal_intelligence.feature_engine`
# (`rsi.py`, `directional_movement.py`, `relative_volume.py`,
# `macd_histogram.py`, `candle_body_ratio.py`).
#
# EXPLICITLY DEFERRED (per the checkpoint directive's own Part 11/12
# instruction not to guess ambiguous semantics):
#   - Delta: the directive's own Gainz description does not disambiguate
#     "volume delta" vs "price delta" vs "tick delta", and no Gainz
#     source exists to check. NOT implemented, NOT registered here.
#   - Breakout: the directive's own Gainz description does not fix
#     lookback / prior-bar-exclusion / direction / threshold conventions
#     unambiguously, and no Gainz source exists to check. NOT
#     implemented, NOT registered here.
# Both remain open, honestly-documented gaps - see taskReport.md and
# `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`'s
# Checkpoint 64.49 section.
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FieldCategory(str, Enum):
    RAW_PRICE = "RAW_PRICE"
    RAW_VOLUME = "RAW_VOLUME"
    DERIVED_FEATURE = "DERIVED_FEATURE"


class FieldDataType(str, Enum):
    DECIMAL = "DECIMAL"
    # Checkpoint 65.07: the categorical sibling to DECIMAL, backing a
    # future `FieldDefinition` whose values are
    # `domain.feature.contracts.CategoricalFeatureValue.category` strings
    # rather than `FeatureValue.value` Decimals - see that module's
    # Checkpoint 65.07 comment for the full rationale. No categorical
    # field is registered in `_FIELDS` this checkpoint (see
    # `market_regime` status in taskReport.md) - this enum member only
    # proves the registry CAN identify a categorical field's data type.
    CATEGORICAL = "CATEGORICAL"


class FieldAvailability(str, Enum):
    """Data-quality classification a field's *source* carries at
    evaluation time - reuses the SAMPLE_BAR/TRADING_GRADE_BAR vocabulary
    established in `docs/architecture/MARKET_DATA_QUALITY_ASSESSMENT.md`
    rather than inventing a parallel one. Every field currently offered
    is backed only by fixture/historical bars (Checkpoint 26's own
    safety-gate requirement - see `strategy_execution.errors` and
    `application/services/strategy_execution.py`), so every entry below
    is `HISTORICAL_AND_SAMPLE`, never `TRADING_GRADE` - there is no
    trading-grade source yet (Checkpoint 25.1)."""

    HISTORICAL_AND_SAMPLE = "HISTORICAL_AND_SAMPLE"


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """One canonical, selectable field. `field_id` is the stable
    identifier a `ParameterDefinition(type=FIELD_REFERENCE)` value stores
    and a strategy's `required_features()` resolves - never a free-text
    display string."""

    field_id: str
    display_name: str
    category: FieldCategory
    data_type: FieldDataType
    source: str
    timeframe_support: str
    required_inputs: tuple[str, ...]
    availability: FieldAvailability
    version: str
    description: str


def _raw(field_id: str, display_name: str, description: str) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id,
        display_name=display_name,
        category=FieldCategory.RAW_PRICE if field_id != "volume" else FieldCategory.RAW_VOLUME,
        data_type=FieldDataType.DECIMAL,
        source="domain.market_data.contracts.Bar",
        timeframe_support="any",
        required_inputs=(),
        availability=FieldAvailability.HISTORICAL_AND_SAMPLE,
        version="v1",
        description=description,
    )


def _derived(
    field_id: str, display_name: str, required_inputs: tuple[str, ...], description: str
) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id,
        display_name=display_name,
        category=FieldCategory.DERIVED_FEATURE,
        data_type=FieldDataType.DECIMAL,
        source="signal_intelligence.feature_engine",
        timeframe_support="any",
        required_inputs=required_inputs,
        availability=FieldAvailability.HISTORICAL_AND_SAMPLE,
        version="v1",
        description=description,
    )


def _derived_categorical(
    field_id: str, display_name: str, required_inputs: tuple[str, ...], description: str
) -> FieldDefinition:
    """Checkpoint 65.08: the categorical sibling of `_derived` - identical
    in every field EXCEPT `data_type`, which is `FieldDataType.CATEGORICAL`
    (its values are `CategoricalFeatureValue.category` strings, never
    `FeatureValue.value` Decimals). First real user of the `CATEGORICAL`
    enum member Checkpoint 65.07 added."""
    return FieldDefinition(
        field_id=field_id,
        display_name=display_name,
        category=FieldCategory.DERIVED_FEATURE,
        data_type=FieldDataType.CATEGORICAL,
        source="signal_intelligence.feature_engine",
        timeframe_support="any",
        required_inputs=required_inputs,
        availability=FieldAvailability.HISTORICAL_AND_SAMPLE,
        version="v1",
        description=description,
    )


_FIELDS: tuple[FieldDefinition, ...] = (
    _raw("open", "Open", "Bar open price."),
    _raw("high", "High", "Bar high price."),
    _raw("low", "Low", "Bar low price."),
    _raw("close", "Close", "Bar close price."),
    _raw("volume", "Volume", "Bar volume (always 0 for SAMPLE_BAR sources - never fabricated)."),
    _derived(
        "sma",
        "Simple Moving Average",
        ("close",),
        "SMA(lookback) over Bar.close, via signal_intelligence.feature_engine.sma.",
    ),
    _derived(
        "ema",
        "Exponential Moving Average",
        ("close",),
        "EMA(lookback) over Bar.close, via signal_intelligence.feature_engine.ema.",
    ),
    _derived(
        "atr",
        "Average True Range",
        ("high", "low", "close"),
        "Wilder ATR(lookback) over Bar OHLC, via signal_intelligence.feature_engine.atr.",
    ),
    _derived(
        "rsi",
        "Relative Strength Index",
        ("close",),
        "Wilder RSI(lookback) over Bar.close, via signal_intelligence.feature_engine.rsi. "
        "Standard TA convention - NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "adx",
        "Average Directional Index",
        ("high", "low", "close"),
        "Wilder ADX(lookback) - Wilder-smoothed average of DX, via "
        "signal_intelligence.feature_engine.directional_movement. Standard TA convention - "
        "NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "plus_di",
        "Plus Directional Indicator (+DI)",
        ("high", "low", "close"),
        "Wilder +DI(lookback), via signal_intelligence.feature_engine.directional_movement. "
        "Standard TA convention - NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "minus_di",
        "Minus Directional Indicator (-DI)",
        ("high", "low", "close"),
        "Wilder -DI(lookback), via signal_intelligence.feature_engine.directional_movement. "
        "Standard TA convention - NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "relative_volume",
        "Relative Volume (RVOL)",
        ("volume",),
        "current_volume / mean(previous lookback bars' volume), via "
        "signal_intelligence.feature_engine.relative_volume. Baseline convention explicitly "
        "chosen (trailing simple average, excludes current bar) - NOT verified against a "
        "Gainz reference (none exists).",
    ),
    _derived(
        "macd_hist",
        "MACD Histogram",
        ("close",),
        "Standard 12/26/9 MACD histogram = MACD_line - signal_line, via "
        "signal_intelligence.feature_engine.macd_histogram, reusing the canonical EMA "
        "implementation for the fast/slow lines. Standard TA convention - NOT verified "
        "against a Gainz reference (none exists).",
    ),
    _derived(
        "candle_body_ratio",
        "Candle Body Ratio",
        ("open", "high", "low", "close"),
        "abs(close - open) / (high - low), skipping zero-range bars, via "
        "signal_intelligence.feature_engine.candle_body_ratio. Standard convention - NOT "
        "verified against a Gainz reference (none exists).",
    ),
    # -------------------------------------------------------------------
    # Checkpoint 64.97 additions - generic engulfing-pattern and N-bar
    # price-delta features. Both are GENERIC, standard candlestick/price
    # concepts, structurally similar to columns in the user-supplied
    # research/rebuild reference file
    # (docs/research/gainz_signal_engine_reference.py, read-only) but NOT
    # claimed to be verified authentic GainzAlgo mathematics - see
    # docs/research/GAINZ_SIGNAL_ENGINE_AUDIT.md for the classification.
    # -------------------------------------------------------------------
    _derived(
        "bullish_engulfing",
        "Bullish Engulfing",
        ("open", "close"),
        "Two-candle bullish engulfing pattern (prior bearish, current bullish, current close > "
        "prior open, current open <= prior close), via "
        "signal_intelligence.feature_engine.bullish_engulfing. Encoded as Decimal 1/0 "
        "(true/false) - FeatureValue.value has no boolean variant. GENERIC candlestick "
        "definition - NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "bearish_engulfing",
        "Bearish Engulfing",
        ("open", "close"),
        "Two-candle bearish engulfing pattern (prior bullish, current bearish, current close < "
        "prior open, current open >= prior close), via "
        "signal_intelligence.feature_engine.bearish_engulfing. Encoded as Decimal 1/0 "
        "(true/false) - FeatureValue.value has no boolean variant. GENERIC candlestick "
        "definition - NOT verified against a Gainz reference (none exists).",
    ),
    _derived(
        "price_delta",
        "Price Delta (N-bar)",
        ("close",),
        "Signed N-bar close-to-close delta: close[t] - close[t-N], via "
        "signal_intelligence.feature_engine.price_delta. Signed-numeric representation chosen "
        "over the reference file's two-boolean-column shape (price_up_delta/price_down_delta) "
        "as the smallest canonical representation a consumer can threshold either way. GENERIC "
        "price feature - NOT verified against a Gainz reference (none exists). Default N=10 is "
        "a REFERENCE-ARTIFACT DEFAULT only (see price_delta.REFERENCE_ARTIFACT_DEFAULT_LOOKBACK), "
        "never a verified Gainz parameter.",
    ),
    # -------------------------------------------------------------------
    # Checkpoint 65.03 addition - Market Context Intelligence's first
    # implemented concept (carried forward from 65.02's audit,
    # docs/research/MARKET_CONTEXT_INTELLIGENCE.md). Signed price-vs-MA
    # divergence - GENERIC, not Gainz-specific, not connected to Gainz
    # this checkpoint. Two field identities (SMA-backed, EMA-backed)
    # because the existing parse_feature_name() convention only strips a
    # trailing run of INTEGER parameters - MA type is categorical, so it
    # is folded into the KIND instead of a parameter (see
    # signal_intelligence.feature_engine.price_vs_ma_pct module docstring
    # for the full design-decision rationale). Both delegate to the SAME
    # canonical SMA/EMA compute functions - no second moving-average
    # engine.
    # -------------------------------------------------------------------
    _derived(
        "price_vs_ma_pct_sma",
        "Price vs SMA (%)",
        ("close",),
        "Signed (close - SMA(lookback)) / SMA(lookback), via "
        "signal_intelligence.feature_engine.price_vs_ma_pct.compute_price_vs_ma_pct_sma, "
        "reusing the canonical SMA implementation. >0 = price above the MA, <0 = below, "
        "=0 = equal - never a boolean. Zero-MA outputs are skipped (never divides by zero). "
        "GENERIC feature, NOT Gainz-specific.",
    ),
    _derived(
        "price_vs_ma_pct_ema",
        "Price vs EMA (%)",
        ("close",),
        "Signed (close - EMA(lookback)) / EMA(lookback), via "
        "signal_intelligence.feature_engine.price_vs_ma_pct.compute_price_vs_ma_pct_ema, "
        "reusing the canonical EMA implementation. >0 = price above the MA, <0 = below, "
        "=0 = equal - never a boolean. Zero-MA outputs are skipped (never divides by zero). "
        "GENERIC feature, NOT Gainz-specific.",
    ),
    # -------------------------------------------------------------------
    # Checkpoint 65.04 addition - Short-Term Rebound Candidate. A generic
    # MARKET CONTEXT feature (NOT a strategy, NOT a BUY/SELL signal,
    # NOT Gainz-specific, NOT performance-validated). Composes THREE
    # already-existing canonical features (price_delta, rsi,
    # bullish_engulfing) by timestamp - see
    # signal_intelligence.feature_engine.rebound_candidate module
    # docstring for the full rule/inclusion-exclusion rationale, and
    # docs/research/MARKET_CONTEXT_INTELLIGENCE.md's Short-Term Rebound
    # section.
    # -------------------------------------------------------------------
    # -------------------------------------------------------------------
    # Checkpoint 65.05 addition - Moving Average Divergence. A generic
    # MARKET CONTEXT feature (NOT a trading signal, NOT a crossover
    # event, NOT Gainz-specific, NOT performance-validated) measuring the
    # normalized relationship between a FAST and a SLOW moving average:
    # (fast_ma - slow_ma) / slow_ma. Two field identities (SMA-vs-SMA,
    # EMA-vs-EMA) - same categorical-MA-type-folded-into-KIND pattern
    # 65.03's `price_vs_ma_pct` established; mixed SMA/EMA pairs are
    # deliberately NOT added - see
    # signal_intelligence.feature_engine.ma_divergence module docstring
    # Part A for the full MA-type-combination-support rationale. Both
    # delegate to the SAME canonical SMA/EMA compute functions - no
    # second moving-average engine. Distinct from the `ema_crossover`
    # STRATEGY - this is purely numeric, no BUY/SELL/HOLD, no crossover-
    # state logic.
    # -------------------------------------------------------------------
    _derived(
        "ma_divergence_sma",
        "Moving Average Divergence (SMA)",
        ("close",),
        "Signed (fast_SMA(fast_lookback) - slow_SMA(slow_lookback)) / slow_SMA(slow_lookback), "
        "via signal_intelligence.feature_engine.ma_divergence.compute_ma_divergence_sma, "
        "reusing the canonical SMA implementation for both legs. fast_lookback must be "
        "strictly less than slow_lookback (validated, never silently swapped). >0 = fast SMA "
        "above slow SMA, <0 = below, =0 = equal - never a boolean, never a crossover-state "
        "value. Zero slow-SMA outputs are skipped (never divides by zero). GENERIC feature, "
        "NOT Gainz-specific, NOT performance-validated, NOT the ema_crossover strategy.",
    ),
    _derived(
        "ma_divergence_ema",
        "Moving Average Divergence (EMA)",
        ("close",),
        "Signed (fast_EMA(fast_lookback) - slow_EMA(slow_lookback)) / slow_EMA(slow_lookback), "
        "via signal_intelligence.feature_engine.ma_divergence.compute_ma_divergence_ema, "
        "reusing the canonical EMA implementation for both legs. fast_lookback must be "
        "strictly less than slow_lookback (validated, never silently swapped). >0 = fast EMA "
        "above slow EMA, <0 = below, =0 = equal - never a boolean, never a crossover-state "
        "value. Zero slow-EMA outputs are skipped (never divides by zero). GENERIC feature, "
        "NOT Gainz-specific, NOT performance-validated, NOT the ema_crossover strategy.",
    ),
    _derived(
        "rebound_candidate",
        "Short-Term Rebound Candidate",
        ("close", "open"),
        "1 if price_delta_N(t) < 0 AND rsi_M(t) < rsi_oversold_threshold AND "
        "bullish_engulfing(t) == 1, else 0 - unavailable (no output) if any dependency has "
        "no value at t, via signal_intelligence.feature_engine.rebound_candidate."
        "compute_rebound_candidate. Encoded as Decimal 1/0 (true/false) - a CONTEXT "
        "condition, NEVER a BUY/SELL/HOLD signal. GENERIC feature, NOT Gainz-specific, NOT "
        "performance-validated - see docs/research/MARKET_CONTEXT_INTELLIGENCE.md.",
    ),
    # -------------------------------------------------------------------
    # Checkpoint 65.08 addition - Market Regime. The first PRODUCTION
    # categorical Market Context feature (`FieldDataType.CATEGORICAL`,
    # `CategoricalFeatureValue` output, NOT `FeatureValue`/Decimal). One
    # field identity - exactly one category value per timestamp, never
    # split into market_regime_bull/bear/sideways/transition. NOT a
    # trading signal, NOT Gainz-specific, NOT performance-validated, NOT
    # breadth/sentiment/index-based, NOT a Fire Sale detector. See
    # signal_intelligence.feature_engine.market_regime module docstring
    # for the full rule/warm-up/edge-case documentation and
    # docs/research/MARKET_CONTEXT_INTELLIGENCE.md section 7&8.
    # -------------------------------------------------------------------
    _derived_categorical(
        "market_regime",
        "Market Regime",
        ("high", "low", "close"),
        "Deterministic BULL/BEAR/SIDEWAYS/TRANSITION classification via "
        "signal_intelligence.feature_engine.market_regime.compute_market_regime. "
        "trend_strength_ok = adx_14 >= ADX_MIN; bull_direction = plus_di_14 > minus_di_14 AND "
        "ema_fast > ema_slow; bear_direction = minus_di_14 > plus_di_14 AND ema_fast < "
        "ema_slow. BULL if trend_strength_ok AND bull_direction; BEAR if trend_strength_ok "
        "AND bear_direction; SIDEWAYS if NOT trend_strength_ok; TRANSITION otherwise. No "
        "output (never a fabricated state) if any of adx_14/plus_di_14/minus_di_14/ema_fast/ "
        "ema_slow is unavailable at a timestamp. ADX_MIN is a RESEARCH DEFAULT parameter, NOT "
        "optimized. GENERIC feature, NOT Gainz-specific, NOT performance-validated, NOT a Fire "
        "Sale detector - see docs/research/MARKET_CONTEXT_INTELLIGENCE.md.",
    ),
)

_FIELDS_BY_ID: dict[str, FieldDefinition] = {f.field_id: f for f in _FIELDS}


def list_fields() -> tuple[FieldDefinition, ...]:
    """Deterministic order (declaration order above) - the frontend
    dropdown must never receive a nondeterministically ordered list."""
    return _FIELDS


def get_field(field_id: str) -> FieldDefinition | None:
    return _FIELDS_BY_ID.get(field_id)


@dataclass(frozen=True, slots=True)
class ResolvedFeatureName:
    """Checkpoint 64.81: the canonical decomposition of ONE resolved
    feature name (what `Strategy.required_features(config)` actually
    returns, e.g. `"ema_12"`, and what `FeatureValue.feature_name`
    actually carries) into the canonical registry `field_id` it refers
    to (`"ema"`) plus the numeric parameters that were baked into the
    name (`(12,)`).

    This exists because `required_features()`'s own docstring calls its
    return values "field_ids (from the canonical field registry)", but
    they are NOT registry field_ids - they are PARAMETERIZED feature
    names. `"ema_12"` is not a key in `_FIELDS_BY_ID`; `"ema"` is. That
    gap is exactly what blocked programmatic Feature->Strategy and
    Feature->Signal correlation (Checkpoint 64.80-F3's gaps 1 and 2),
    and it is closed here by RESOLVING the name through the same
    algorithm the platform already uses, never by guessing from a
    display label.

    `field_id` is `None` when the name does not resolve to a registered
    field - an honest absence (the same discipline
    `build_signal_evidence()` already applies by returning `None` for an
    unregistered strategy), never a fabricated identifier.
    """

    feature_name: str
    field_id: str | None
    parameters: tuple[int, ...]


def parse_feature_name(feature_name: str) -> tuple[str, tuple[int, ...]]:
    """Splits a resolved feature name into its `(kind, numeric params)`
    pair - `"ema_12"` -> `("ema", (12,))`, `"macd_hist_12_26_9"` ->
    `("macd_hist", (12, 26, 9))`, `"candle_body_ratio"` ->
    `("candle_body_ratio", ())`.

    This is the EXACT algorithm `application.services.strategy_execution.
    compute_feature_series()` has used since Checkpoint 64.49 (strip the
    SUFFIX of trailing all-digit segments, everything before it is the
    kind - multi-word kinds like `"plus_di"`/`"relative_volume"` are why
    a single first-`_`-partition is not sufficient). It is LIFTED here,
    not copied: that function now calls this one, so exactly one parse
    exists in the platform and the resolver below can never drift from
    the dispatcher that actually computes the feature.
    """
    parts = feature_name.split("_")
    numeric_from = len(parts)
    while numeric_from > 0 and parts[numeric_from - 1].isdigit():
        numeric_from -= 1
    kind = "_".join(parts[:numeric_from])
    return kind, tuple(int(p) for p in parts[numeric_from:])


def resolve_feature_name(feature_name: str) -> ResolvedFeatureName:
    """Resolves a parameterized feature name to its canonical registry
    `field_id`. Raw OHLCV names (`"close"`) resolve to themselves (they
    carry no parameters and ARE registry field_ids already).

    NEVER guesses: the parsed kind must be a real key in the registry,
    otherwise `field_id` is `None`.
    """
    kind, parameters = parse_feature_name(feature_name)
    return ResolvedFeatureName(
        feature_name=feature_name,
        field_id=kind if kind in _FIELDS_BY_ID else None,
        parameters=parameters,
    )


def is_parameterized_feature(field_id: str) -> bool:
    """True for fields that require a `lookback` parameter (SMA/EMA/ATR),
    false for raw OHLCV fields - used by the parameter-schema builder to
    decide whether a FIELD_REFERENCE parameter also needs an accompanying
    lookback parameter."""
    field = get_field(field_id)
    return field is not None and field.category == FieldCategory.DERIVED_FEATURE
