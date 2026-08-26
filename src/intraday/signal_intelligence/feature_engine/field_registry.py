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
