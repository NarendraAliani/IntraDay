# File: src/intraday/trading_engine/strategy_execution/strategies/atr_volatility_breakout.py
#
# Checkpoint 26: ATR Volatility Breakout - volatility-threshold shape,
# distinct from both the crossover and trend-filter strategies. Uses
# only `signal_intelligence.feature_engine.atr` (existing, tested).
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

STRATEGY_ID = "atr_volatility_breakout"
DISPLAY_NAME = "ATR Volatility Breakout"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"


class AtrVolatilityBreakoutStrategy:
    """BULLISH when the bar's true-range move (close - prior close,
    approximated here as close - open of the same bar) exceeds
    `atr_multiplier * ATR` to the upside; BEARISH symmetrically to the
    downside; NEUTRAL otherwise. A volatility-based shape - reacts to the
    *magnitude* of a move relative to ATR, not to a moving-average
    relationship, deliberately different from both other strategies."""

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="lookback",
                    label="ATR Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Wilder smoothing period N for ATR.",
                ),
                ParameterDefinition(
                    parameter_id="atr_multiplier",
                    label="ATR Multiplier",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=None,
                    minimum=0,
                    maximum=10,
                    help_text="Breakout threshold as a multiple of ATR.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        lookback = require_int(config.values, "lookback")
        return (f"atr_{lookback}",)

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        (atr_name,) = self.required_features(config)
        atr = feature_values.get(atr_name)
        if atr is None:
            return None

        atr_multiplier = require_decimal(config.values, "atr_multiplier")
        move = bar.close - bar.open
        threshold = atr.value * atr_multiplier

        if move > threshold:
            direction = StrategyDirection.BULLISH
        elif move < -threshold:
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
            price=bar.close,
            evidence=(atr,),
        )
