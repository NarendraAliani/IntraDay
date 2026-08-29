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


# ---------------------------------------------------------------------------
# Checkpoint 64.97 addition - Price Delta. Same one-off-dataclass-per-
# identity pattern as every definition above. `lookback` here means the
# N-bar close-to-close offset (`price_delta_N = close[t] - close[t-N]`),
# see `signal_intelligence.feature_engine.price_delta` for the full
# formula/warm-up/representation-choice documentation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceDeltaDefinition:
    """Identifies one parameterized N-bar price delta -
    `feature_name` "price_delta_10" for `PriceDeltaDefinition(10)`. N=10
    is used ONLY as a REFERENCE-ARTIFACT DEFAULT (see
    `price_delta.REFERENCE_ARTIFACT_DEFAULT_LOOKBACK`'s own docstring) -
    it is NOT a verified Gainz parameter and is not defaulted here; every
    caller must supply `lookback` explicitly."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="PriceDeltaDefinition")

    @property
    def feature_name(self) -> str:
        return f"price_delta_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


# ---------------------------------------------------------------------------
# Checkpoint 65.03 additions - Price vs Moving Average Percentage. Two
# identities (SMA-backed, EMA-backed), same one-off-dataclass-per-
# identity pattern as every definition above. See
# `signal_intelligence.feature_engine.price_vs_ma_pct` module docstring
# for the full formula/warm-up/design-decision documentation, in
# particular why MA type is folded into the identity's KIND rather than
# a numeric parameter (the existing `parse_feature_name()` convention
# only strips a trailing run of INTEGER params).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceVsMaPctSmaDefinition:
    """Identifies one parameterized `price_vs_ma_pct` computed against the
    canonical SMA - `feature_name` "price_vs_ma_pct_sma_20" for
    `PriceVsMaPctSmaDefinition(20)`. Delegates its actual moving average
    to `SimpleMovingAverageDefinition(lookback)` (via `sma_definition`) -
    no second moving-average engine, no duplicated warm-up rule."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="PriceVsMaPctSmaDefinition")

    @property
    def sma_definition(self) -> SimpleMovingAverageDefinition:
        return SimpleMovingAverageDefinition(self.lookback)

    @property
    def feature_name(self) -> str:
        return f"price_vs_ma_pct_sma_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class PriceVsMaPctEmaDefinition:
    """Identifies one parameterized `price_vs_ma_pct` computed against the
    canonical EMA - `feature_name` "price_vs_ma_pct_ema_20" for
    `PriceVsMaPctEmaDefinition(20)`. Delegates its actual moving average
    to `ExponentialMovingAverageDefinition(lookback)` (via
    `ema_definition`) - no second moving-average engine, no duplicated
    warm-up rule."""

    lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.lookback, owner="PriceVsMaPctEmaDefinition")

    @property
    def ema_definition(self) -> ExponentialMovingAverageDefinition:
        return ExponentialMovingAverageDefinition(self.lookback)

    @property
    def feature_name(self) -> str:
        return f"price_vs_ma_pct_ema_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


# ---------------------------------------------------------------------------
# Checkpoint 65.04 addition - Short-Term Rebound Candidate. A generic
# MARKET CONTEXT feature (NOT a strategy, NOT a BUY/SELL signal) that
# composes THREE already-existing canonical features
# (`price_delta`, `rsi`, `bullish_engulfing`) rather than recalculating
# any of their mathematics - see
# `signal_intelligence.feature_engine.rebound_candidate` module docstring
# for the full rule/rationale, and
# `docs/research/MARKET_CONTEXT_INTELLIGENCE.md`'s Short-Term Rebound
# section for the research-level documentation.
#
# All three parameters are numeric, so this identity fits the EXISTING
# `parse_feature_name()` trailing-integer-suffix convention exactly like
# `macd_hist_12_26_9` - no categorical-parameter problem like MA-type
# arises here (unlike `price_vs_ma_pct`), so only ONE field identity is
# needed, not two.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Checkpoint 65.05 additions - Moving Average Divergence. Two identities
# (SMA-vs-SMA, EMA-vs-EMA) - same "categorical MA-type folded into the
# KIND, numeric lookbacks stay as trailing parameters" pattern 65.03
# established for `price_vs_ma_pct`. See
# `signal_intelligence.feature_engine.ma_divergence` module docstring for
# the full formula/warm-up/MA-type-support-decision documentation - in
# particular why mixed SMA/EMA pairs are NOT added as a third/fourth
# identity this checkpoint.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaDivergenceSmaDefinition:
    """Identifies one parameterized `ma_divergence` computed between two
    canonical SMAs - `feature_name` "ma_divergence_sma_9_20" for
    `MaDivergenceSmaDefinition(fast_lookback=9, slow_lookback=20)`.
    Delegates both moving averages to `SimpleMovingAverageDefinition` (via
    `fast_sma_definition`/`slow_sma_definition`) - no second moving-average
    engine, no duplicated warm-up rule.

    `fast_lookback` must be strictly less than `slow_lookback` - fast and
    slow are never silently swapped."""

    fast_lookback: int
    slow_lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.fast_lookback, owner="MaDivergenceSmaDefinition.fast_lookback")
        _validate_lookback(self.slow_lookback, owner="MaDivergenceSmaDefinition.slow_lookback")
        if self.fast_lookback >= self.slow_lookback:
            raise InvalidLookbackError(
                "MaDivergenceSmaDefinition.fast_lookback must be strictly less than "
                f"slow_lookback, got fast={self.fast_lookback} slow={self.slow_lookback}"
            )

    @property
    def fast_sma_definition(self) -> SimpleMovingAverageDefinition:
        return SimpleMovingAverageDefinition(self.fast_lookback)

    @property
    def slow_sma_definition(self) -> SimpleMovingAverageDefinition:
        return SimpleMovingAverageDefinition(self.slow_lookback)

    @property
    def feature_name(self) -> str:
        return f"ma_divergence_sma_{self.fast_lookback}_{self.slow_lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class MaDivergenceEmaDefinition:
    """Identifies one parameterized `ma_divergence` computed between two
    canonical EMAs - `feature_name` "ma_divergence_ema_9_20" for
    `MaDivergenceEmaDefinition(fast_lookback=9, slow_lookback=20)`.
    Delegates both moving averages to `ExponentialMovingAverageDefinition`
    (via `fast_ema_definition`/`slow_ema_definition`) - no second moving-
    average engine, no duplicated warm-up rule.

    `fast_lookback` must be strictly less than `slow_lookback` - fast and
    slow are never silently swapped."""

    fast_lookback: int
    slow_lookback: int

    def __post_init__(self) -> None:
        _validate_lookback(self.fast_lookback, owner="MaDivergenceEmaDefinition.fast_lookback")
        _validate_lookback(self.slow_lookback, owner="MaDivergenceEmaDefinition.slow_lookback")
        if self.fast_lookback >= self.slow_lookback:
            raise InvalidLookbackError(
                "MaDivergenceEmaDefinition.fast_lookback must be strictly less than "
                f"slow_lookback, got fast={self.fast_lookback} slow={self.slow_lookback}"
            )

    @property
    def fast_ema_definition(self) -> ExponentialMovingAverageDefinition:
        return ExponentialMovingAverageDefinition(self.fast_lookback)

    @property
    def slow_ema_definition(self) -> ExponentialMovingAverageDefinition:
        return ExponentialMovingAverageDefinition(self.slow_lookback)

    @property
    def feature_name(self) -> str:
        return f"ma_divergence_ema_{self.fast_lookback}_{self.slow_lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class ReboundCandidateDefinition:
    """Identifies one parameterized `rebound_candidate` -
    `feature_name` "rebound_candidate_10_14_30" for
    `ReboundCandidateDefinition(delta_lookback=10, rsi_lookback=14,
    rsi_oversold_threshold=30)`. Delegates its three dependency
    calculations to `PriceDeltaDefinition(delta_lookback)`,
    `RelativeStrengthIndexDefinition(rsi_lookback)`, and the existing
    `compute_bullish_engulfing` (no parameters of its own) - no
    duplicated math, no second warm-up rule.

    `rsi_oversold_threshold` is a plain integer in [0, 100] (RSI's own
    native range) compared against the RSI dependency's raw output - it
    is a CONDITION parameter, not a Gainz weight or an optimized
    threshold (none of this checkpoint's default values were tuned
    against any performance data - see the feature module's own
    docstring for the RESEARCH DEFAULT classification)."""

    delta_lookback: int
    rsi_lookback: int
    rsi_oversold_threshold: int

    def __post_init__(self) -> None:
        _validate_lookback(self.delta_lookback, owner="ReboundCandidateDefinition.delta_lookback")
        _validate_lookback(self.rsi_lookback, owner="ReboundCandidateDefinition.rsi_lookback")
        if isinstance(self.rsi_oversold_threshold, bool) or not isinstance(
            self.rsi_oversold_threshold, int
        ):
            raise InvalidLookbackError(
                "ReboundCandidateDefinition.rsi_oversold_threshold must be an int, "
                f"got {self.rsi_oversold_threshold!r}"
            )
        if not (0 <= self.rsi_oversold_threshold <= 100):
            raise InvalidLookbackError(
                "ReboundCandidateDefinition.rsi_oversold_threshold must be in [0, 100], "
                f"got {self.rsi_oversold_threshold}"
            )

    @property
    def price_delta_definition(self) -> PriceDeltaDefinition:
        return PriceDeltaDefinition(self.delta_lookback)

    @property
    def rsi_definition(self) -> RelativeStrengthIndexDefinition:
        return RelativeStrengthIndexDefinition(self.rsi_lookback)

    @property
    def feature_name(self) -> str:
        return (
            f"rebound_candidate_{self.delta_lookback}_{self.rsi_lookback}_"
            f"{self.rsi_oversold_threshold}"
        )

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION


# ---------------------------------------------------------------------------
# Checkpoint 65.08 addition - Market Regime. The first PRODUCTION
# CATEGORICAL feature identity, using the `CategoricalFeatureValue`/
# `FieldDataType.CATEGORICAL` seam Checkpoint 65.07 built. Implements the
# rule already DESIGNED (not re-derived) in 65.06 - see
# `signal_intelligence.feature_engine.market_regime` module docstring for
# the full rule/warm-up/no-lookahead/edge-case documentation, and
# `docs/research/MARKET_CONTEXT_INTELLIGENCE.md` section 7&8.
#
# THREE numeric parameters (`adx_min`, `ema_fast_lookback`,
# `ema_slow_lookback`) fit the existing `parse_feature_name()` trailing-
# integer-suffix convention exactly like `rebound_candidate`'s three
# parameters - no categorical-parameter problem arises (unlike
# `price_vs_ma_pct`'s MA-type slot), so only ONE field identity is needed.
# The canonical ADX/+DI/-DI smoothing period is FIXED at 14 (not a
# parameter of this definition) - see the feature module's own docstring
# for why.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarketRegimeDefinition:
    """Identifies one parameterized `market_regime` - `feature_name`
    "market_regime_20_9_20" for `MarketRegimeDefinition(adx_min=20,
    ema_fast_lookback=9, ema_slow_lookback=20)`. Delegates its EMA legs to
    `ExponentialMovingAverageDefinition` and its ADX/+DI/-DI dependency to
    `DirectionalMovementDefinition(14)` (fixed - see
    `market_regime.CANONICAL_ADX_DI_LOOKBACK`) - no second moving-average
    or directional-movement engine, no duplicated warm-up rule.

    `adx_min` is a RESEARCH DEFAULT THRESHOLD supplied explicitly by every
    caller - never auto-applied, never optimized against any performance
    data by this checkpoint (see the feature module's own docstring).
    `ema_fast_lookback` must be strictly less than `ema_slow_lookback` -
    fast and slow are never silently swapped."""

    adx_min: int
    ema_fast_lookback: int
    ema_slow_lookback: int

    def __post_init__(self) -> None:
        if isinstance(self.adx_min, bool) or not isinstance(self.adx_min, int):
            raise InvalidLookbackError(
                f"MarketRegimeDefinition.adx_min must be an int, got {self.adx_min!r}"
            )
        if self.adx_min <= 0:
            raise InvalidLookbackError(
                f"MarketRegimeDefinition.adx_min must be positive, got {self.adx_min}"
            )
        _validate_lookback(self.ema_fast_lookback, owner="MarketRegimeDefinition.ema_fast_lookback")
        _validate_lookback(self.ema_slow_lookback, owner="MarketRegimeDefinition.ema_slow_lookback")
        if self.ema_fast_lookback >= self.ema_slow_lookback:
            raise InvalidLookbackError(
                "MarketRegimeDefinition.ema_fast_lookback must be strictly less than "
                f"ema_slow_lookback, got fast={self.ema_fast_lookback} "
                f"slow={self.ema_slow_lookback}"
            )

    @property
    def ema_fast_definition(self) -> ExponentialMovingAverageDefinition:
        return ExponentialMovingAverageDefinition(self.ema_fast_lookback)

    @property
    def ema_slow_definition(self) -> ExponentialMovingAverageDefinition:
        return ExponentialMovingAverageDefinition(self.ema_slow_lookback)

    @property
    def feature_name(self) -> str:
        return f"market_regime_{self.adx_min}_{self.ema_fast_lookback}_{self.ema_slow_lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION
