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
