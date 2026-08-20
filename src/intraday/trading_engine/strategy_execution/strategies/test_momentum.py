# File: src/intraday/trading_engine/strategy_execution/strategies/test_momentum.py
#
# Checkpoint 64.20 §8: TEST_MOMENTUM — a deliberately trivial,
# deterministic strategy whose ONLY purpose is proof-of-extensibility.
# It is NOT a production trading strategy, is NEVER registered in
# `registry.build_default_registry()` (verified by a dedicated test),
# and must never appear in the real strategy list an operator sees.
#
# Rule (deliberately simple - the point is the ARCHITECTURE, not the
# signal quality, per this checkpoint's own explicit instruction):
# BULLISH when close is more than `threshold_percent` above a short
# EMA; BEARISH when more than `threshold_percent` below it; NEUTRAL
# otherwise - structurally identical in SHAPE to the real
# `SmaTrendFilterStrategy` (price vs. one already-computed feature),
# proving a new strategy can reuse the EXISTING generic `ema_<lookback>`
# feature family (`compute_feature_series()`,
# `application/services/strategy_execution.py`) without that dispatcher
# needing a single line changed.
from __future__ import annotations

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.trading_engine.strategy_execution.contracts import (
    ParameterDefinition,
    ParameterType,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyParameterSchema,
    StrategySignal,
    require_decimal,
    require_int,
)

STRATEGY_ID = "test_momentum"
DISPLAY_NAME = "TEST_MOMENTUM (NON-PRODUCTION - architecture validation only)"
SPECIFICATION_VERSION = "test-v1"
CODE_VERSION = "test-v1"


class TestMomentumStrategy:
    """NON_PRODUCTION / TEST_ONLY. Never registered in
    `build_default_registry()` - constructed only inside
    `tests/unit/trading_engine/test_strategy_extensibility.py`'s own
    local `StrategyRegistry()`, exactly how a real new strategy would
    be registered for its OWN tests before being added to production.
    Deliberately produces no TradePlan (directional-only, same shape as
    `EmaCrossoverStrategy`) - TradePlan optionality is already proven by
    that real strategy, this one does not need to re-prove it."""

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="ema_lookback",
                    label="EMA Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=3,
                    minimum=1,
                    maximum=50,
                    help_text="Period of the reference EMA (test strategy only).",
                ),
                ParameterDefinition(
                    parameter_id="threshold_percent",
                    label="Threshold (%)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=0.1,
                    minimum=0,
                    maximum=10,
                    help_text="Percent distance from the EMA required before a direction is "
                    "declared (test strategy only).",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        lookback = require_int(config.values, "ema_lookback")
        return (f"ema_{lookback}",)

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        (ema_name,) = self.required_features(config)
        ema = feature_values.get(ema_name)
        if ema is None:
            return None

        threshold_percent = require_decimal(config.values, "threshold_percent")
        price = bar.close
        band = ema.value * threshold_percent / 100

        if price > ema.value + band:
            direction = StrategyDirection.BULLISH
        elif price < ema.value - band:
            direction = StrategyDirection.BEARISH
        else:
            direction = StrategyDirection.NEUTRAL

        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version=config.configuration_version,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=price,
            evidence=(ema,),
        )


__all__ = ["TestMomentumStrategy"]
