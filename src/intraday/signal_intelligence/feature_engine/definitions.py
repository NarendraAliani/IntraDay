# File: src/intraday/signal_intelligence/feature_engine/definitions.py
#
# Checkpoint 15: feature identity. A `SimpleMovingAverageDefinition` is
# the smallest useful representation of "which parameterized feature is
# this" — just the one parameter SMA actually has (`lookback`) plus a
# deterministic derivation of the `feature_name`/`feature_version` pair
# `domain.feature.contracts.FeatureValue` already uses as its identity
# (Checkpoint 5's own convention: `FeatureValue`'s docstring gives
# "ema_20" as the worked example of a name baking its parameter in).
#
# Deliberately NOT a generic `FeatureDefinition` framework/registry: only
# SMA exists this checkpoint. A future EMA/RSI/ATR definition follows the
# same small, one-off pattern shown here — its own tiny dataclass with a
# `feature_name`/`feature_version` property — rather than this checkpoint
# building a parameterization framework speculatively ahead of a second
# concrete feature actually needing one.
#
# Checkpoint 16 adds `ExponentialMovingAverageDefinition` following the
# identical, proven pattern — no registry was introduced even now that a
# second feature exists, confirming the Checkpoint 15 prediction that this
# one-off shape scales without a framework.
#
# Checkpoint 17 adds `AverageTrueRangeDefinition` — same pattern again, a
# third confirmation. ATR's `lookback` means the Wilder smoothing period
# `N`, distinct in meaning from SMA's fixed-window size or EMA's period,
# but identical in *shape* (a single positive-integer parameter) — no
# change to the identity pattern was needed to accommodate ATR's very
# different calculation (OHLC + previous close, not close-only).
from __future__ import annotations

from dataclasses import dataclass

from intraday.domain.shared_kernel.contracts import Version
from intraday.signal_intelligence.feature_engine.errors import InvalidLookbackError

# The feature-engine implementation's own version, not a per-feature one -
# bumped only if a calculation's own semantics change (e.g. a rounding-
# policy change), never mechanically. Distinct from `pyproject.toml`'s
# package version and `SPECTACULAR_SETTINGS["VERSION"]` (no API surface
# exists for this bounded context at Checkpoint 16 either).
FEATURE_ENGINE_VERSION = Version(value="v1")


def _validate_lookback(lookback: object, *, owner: str) -> None:
    """Shared validation for any feature identity whose sole parameter is
    a positive lookback/period count. Kept as a small module-level helper
    (not a class, not a registry) rather than duplicated across
    `SimpleMovingAverageDefinition`/`ExponentialMovingAverageDefinition` -
    the smallest amount of sharing that avoids literal duplication without
    building a generic definition base class nothing else needs yet."""
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise InvalidLookbackError(f"{owner}.lookback must be an int, got {lookback!r}")
    if lookback <= 0:
        raise InvalidLookbackError(f"{owner}.lookback must be positive, got {lookback}")


@dataclass(frozen=True, slots=True)
class SimpleMovingAverageDefinition:
    """Identifies one parameterized SMA - `SimpleMovingAverageDefinition(5)`
    and `SimpleMovingAverageDefinition(10)` are distinct, reproducible
    identities (`feature_name` "sma_5" vs "sma_10"); two definitions
    constructed with the same `lookback` are equal and produce the same
    `feature_name` (Checkpoint 15 §4)."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="SimpleMovingAverageDefinition")

    @property
    def feature_name(self) -> str:
        return f"sma_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class ExponentialMovingAverageDefinition:
    """Identifies one parameterized EMA - `ExponentialMovingAverageDefinition(5)`
    and `ExponentialMovingAverageDefinition(10)` are distinct, reproducible
    identities (`feature_name` "ema_5" vs "ema_10" - the exact worked
    example `FeatureValue`'s own Checkpoint 5 docstring gives); two
    definitions constructed with the same `lookback` are equal and produce
    the same `feature_name` (Checkpoint 16, following Checkpoint 15 §4's
    precedent exactly).

    `lookback` here means the EMA's period `N` (used to derive
    `alpha = 2 / (N + 1)` and to size the seed window - see
    `signal_intelligence.feature_engine.ema` for the full seed/recurrence
    documentation). Named `lookback`, not `period`, to keep the identity
    field name consistent with `SimpleMovingAverageDefinition` - EMA
    technically "looks back" indefinitely via its recursive term, but the
    seed window is still bounded by this same single integer parameter."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="ExponentialMovingAverageDefinition")

    @property
    def feature_name(self) -> str:
        return f"ema_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class AverageTrueRangeDefinition:
    """Identifies one parameterized ATR - `AverageTrueRangeDefinition(14)`
    is the conventional "ATR(14)", `feature_name` "atr_14". Two
    definitions with the same `lookback` are equal and produce the same
    `feature_name` (Checkpoint 17, following Checkpoint 15 §4/Checkpoint
    16's identical precedent).

    `lookback` here means the Wilder smoothing period `N` - see
    `signal_intelligence.feature_engine.atr` for the full True Range/
    seed/recurrence/warm-up documentation."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="AverageTrueRangeDefinition")

    @property
    def feature_name(self) -> str:
        return f"atr_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


# ---------------------------------------------------------------------------
# Checkpoint 64.49 additions - RSI/ADX+DI-DI/Relative Volume/MACD Histogram.
# Same one-off-dataclass-per-identity pattern as SMA/EMA/ATR above - no
# generic `FeatureDefinition` framework introduced even now that 7
# features exist, confirming the Checkpoint 15 prediction again. Candle
# Body Ratio has no parameters at all (see `candle_body_ratio.py`'s own
# `CANDLE_BODY_RATIO_FIELD_ID` constant - no dataclass needed for a
# zero-parameter identity).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelativeStrengthIndexDefinition:
    """Identifies one parameterized Wilder RSI - `feature_name` "rsi_14"
    for `RelativeStrengthIndexDefinition(14)`. See
    `signal_intelligence.feature_engine.rsi` for the full formula/seed/
    warm-up documentation and the explicit "standard convention, not
    Gainz-verified" caveat."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="RelativeStrengthIndexDefinition")

    @property
    def feature_name(self) -> str:
        return f"rsi_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class DirectionalMovementDefinition:
    """Identifies one parameterized Wilder directional-movement family -
    a SINGLE `lookback` drives all three related fields (`plus_di_14`,
    `minus_di_14`, `adx_14`), matching the standard convention that the
    DI smoothing period and the ADX-of-DX smoothing period are the same
    N. See `signal_intelligence.feature_engine.directional_movement` for
    the full formula/seed/warm-up documentation."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="DirectionalMovementDefinition")

    @property
    def plus_di_feature_name(self) -> str:
        return f"plus_di_{self.lookback}"

    @property
    def minus_di_feature_name(self) -> str:
        return f"minus_di_{self.lookback}"

    @property
    def adx_feature_name(self) -> str:
        return f"adx_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class RelativeVolumeDefinition:
    """Identifies one parameterized Relative Volume (RVOL) -
    `feature_name` "relative_volume_20" for
    `RelativeVolumeDefinition(20)`. See
    `signal_intelligence.feature_engine.relative_volume` for the full
    baseline-choice rationale and missing-data behavior."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="RelativeVolumeDefinition")

    @property
    def feature_name(self) -> str:
        return f"relative_volume_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class MacdHistogramDefinition:
    """Identifies one parameterized MACD Histogram - default 12/26/9
    (`feature_name` "macd_hist_12_26_9"). See
    `signal_intelligence.feature_engine.macd_histogram` for the full
    formula and the EMA-reuse rationale (why the signal line cannot
    literally reuse the Bar-taking canonical EMA function)."""

    fast_lookback: int = 12
    slow_lookback: int = 26
    signal_lookback: int = 9

    def __post_init__(self) -> None:
        _validate_lookback(self.fast_lookback, owner="MacdHistogramDefinition.fast_lookback")
        _validate_lookback(self.slow_lookback, owner="MacdHistogramDefinition.slow_lookback")
        _validate_lookback(self.signal_lookback, owner="MacdHistogramDefinition.signal_lookback")
        if self.fast_lookback >= self.slow_lookback:
            raise InvalidLookbackError(
                "MacdHistogramDefinition.fast_lookback must be strictly less than "
                f"slow_lookback, got fast={self.fast_lookback} slow={self.slow_lookback}"
            )

    @property
    def feature_name(self) -> str:
        return f"macd_hist_{self.fast_lookback}_{self.slow_lookback}_{self.signal_lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION
