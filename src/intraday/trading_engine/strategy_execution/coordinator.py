# File: src/intraday/trading_engine/strategy_execution/coordinator.py
#
# Checkpoint 26 Part 9: multi-strategy execution coordinator. Computes
# each distinct required feature exactly once across all active
# strategies (shared-feature reuse - Part 9/25), then evaluates every
# strategy independently with per-strategy failure isolation (one
# strategy raising never prevents the others from producing a signal -
# Part 9's "one strategy failure must not corrupt another"). No strategy
# ever calls another strategy or this coordinator.
#
# `compute_feature_series` is INJECTED (a plain callable), not imported.
# The actual SMA/EMA/ATR computation lives in
# `signal_intelligence.feature_engine`, and `.importlinter` contract 4
# ("Bounded-context independence") forbids `intraday.trading_engine`
# from importing `intraday.signal_intelligence` at all - re-verified
# live during this checkpoint's Part 2 audit, which caught (and this
# file's own history reflects the fix for) an earlier draft importing
# `feature_engine.sma`/`.ema`/`.atr` directly here. Dependency injection
# keeps this module free of that import while still letting the real
# dispatcher (`application.services.strategy_execution.
# compute_feature_series`, where cross-bounded-context composition is
# architecturally permitted per `.importlinter` contract 3's layering)
# supply the real implementation.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategySignal,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry

FeatureSeriesComputer = Callable[[str, tuple[Bar, ...]], tuple[FeatureValue, ...]]


@dataclass(frozen=True, slots=True)
class StrategyExecutionFailure:
    strategy_id: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class CoordinatorResult:
    signals: tuple[StrategySignal, ...]
    failures: tuple[StrategyExecutionFailure, ...] = field(default_factory=tuple)


class StrategyExecutionCoordinator:
    def __init__(
        self, registry: StrategyRegistry, compute_feature_series: FeatureSeriesComputer
    ) -> None:
        self._registry = registry
        self._compute_feature_series = compute_feature_series

    def run(
        self,
        bars: tuple[Bar, ...],
        configurations: dict[str, StrategyConfigurationValues],
    ) -> CoordinatorResult:
        """Evaluates every active strategy against the LAST bar in
        `bars`, using the full series for feature warm-up. `configurations`
        maps strategy_id -> its configuration values (must cover every
        active strategy)."""
        if not bars:
            return CoordinatorResult(signals=())

        active = self._registry.get_active()

        # Compute the union of required feature field_ids across all
        # active strategies exactly once each (shared-feature reuse).
        feature_series_cache: dict[str, tuple[FeatureValue, ...]] = {}
        for strategy in active:
            config = configurations.get(strategy.strategy_id)
            if config is None:
                continue
            for field_id in strategy.required_features(config):
                if field_id not in feature_series_cache:
                    feature_series_cache[field_id] = self._compute_feature_series(field_id, bars)

        latest_bar = bars[-1]
        latest_features: dict[str, FeatureValue] = {}
        for field_id, series in feature_series_cache.items():
            for fv in series:
                if fv.timestamp == latest_bar.timestamp:
                    latest_features[field_id] = fv
                    break

        signals: list[StrategySignal] = []
        failures: list[StrategyExecutionFailure] = []

        for strategy in active:
            config = configurations.get(strategy.strategy_id)
            if config is None:
                continue
            try:
                required = strategy.required_features(config)
                strategy_features = {
                    fid: latest_features[fid] for fid in required if fid in latest_features
                }
                signal = strategy.evaluate(latest_bar, strategy_features, config)
            except Exception as exc:  # noqa: BLE001 - deliberate isolation boundary
                failures.append(
                    StrategyExecutionFailure(
                        strategy_id=strategy.strategy_id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue

            if signal is not None:
                signals.append(signal)

        return CoordinatorResult(signals=tuple(signals), failures=tuple(failures))
