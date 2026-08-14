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
)

_FIELDS_BY_ID: dict[str, FieldDefinition] = {f.field_id: f for f in _FIELDS}


def list_fields() -> tuple[FieldDefinition, ...]:
    """Deterministic order (declaration order above) - the frontend
    dropdown must never receive a nondeterministically ordered list."""
    return _FIELDS


def get_field(field_id: str) -> FieldDefinition | None:
    return _FIELDS_BY_ID.get(field_id)


def is_parameterized_feature(field_id: str) -> bool:
    """True for fields that require a `lookback` parameter (SMA/EMA/ATR),
    false for raw OHLCV fields - used by the parameter-schema builder to
    decide whether a FIELD_REFERENCE parameter also needs an accompanying
    lookback parameter."""
    field = get_field(field_id)
    return field is not None and field.category == FieldCategory.DERIVED_FEATURE
