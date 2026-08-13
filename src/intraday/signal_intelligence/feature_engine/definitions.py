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
from __future__ import annotations

from dataclasses import dataclass

from intraday.domain.shared_kernel.contracts import Version
from intraday.signal_intelligence.feature_engine.errors import InvalidLookbackError

# The feature-engine implementation's own version, not a per-feature one -
# bumped only if the SMA calculation's own semantics change (e.g. a
# rounding-policy change), never mechanically. Distinct from
# `pyproject.toml`'s package version and `SPECTACULAR_SETTINGS["VERSION"]`
# (this checkpoint touches neither - no API surface exists for this).
FEATURE_ENGINE_VERSION = Version(value="v1")


@dataclass(frozen=True, slots=True)
class SimpleMovingAverageDefinition:
    """Identifies one parameterized SMA - `SimpleMovingAverageDefinition(5)`
    and `SimpleMovingAverageDefinition(10)` are distinct, reproducible
    identities (`feature_name` "sma_5" vs "sma_10"); two definitions
    constructed with the same `lookback` are equal and produce the same
    `feature_name` (Checkpoint 15 §4)."""

    lookback: int

    def __post_init__(self) -> None:
        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int):
            raise InvalidLookbackError(
                f"SimpleMovingAverageDefinition.lookback must be an int, got {self.lookback!r}"
            )
        if self.lookback <= 0:
            raise InvalidLookbackError(
                f"SimpleMovingAverageDefinition.lookback must be positive, got {self.lookback}"
            )

    @property
    def feature_name(self) -> str:
        return f"sma_{self.lookback}"

    @property
    def feature_version(self) -> Version:
        return FEATURE_ENGINE_VERSION
