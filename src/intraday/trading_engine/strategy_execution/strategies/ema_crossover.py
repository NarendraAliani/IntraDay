# File: src/intraday/trading_engine/strategy_execution/strategies/ema_crossover.py
#
# Checkpoint 26: EMA Crossover - trend-following, two-EMA crossover
# shape. Uses only `signal_intelligence.feature_engine.ema` (existing,
# tested); no new indicator implemented.
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
    require_int,
)

STRATEGY_ID = "ema_crossover"
DISPLAY_NAME = "EMA Crossover"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"


class EmaCrossoverStrategy:
    """BULLISH when the fast EMA is above the slow EMA and price is above
    the fast EMA; BEARISH when the fast EMA is below the slow EMA and
    price is below the fast EMA; NEUTRAL otherwise. Deliberately similar
    in spirit to (but structurally distinct from, and independently
    configurable versus) `signal_generation.directional`'s fixed rule -
    that module remains untouched."""

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        # Checkpoint 64.17 §13/§14: `default` below is the ONE canonical
        # source of truth for a NEW configuration's starting values - the
        # API (`strategy_configuration_views.py`), the generated
        # TypeScript contract, and `ParameterSchemaFields.tsx` all read
        # this field directly, never a duplicated default dictionary
        # elsewhere. 12/26 is the CONSERVATIVE BASELINE research starting
        # point (not a claim of optimal profitability - see
        # docs/research/STRATEGY_DEFAULT_PROFILES.md). Changing this
        # value affects only NEW `StrategyConfigurationRecord` rows
        # created after this change - every existing, already-versioned
        # configuration keeps its own stored values unchanged (proven by
        # `test_changing_a_default_does_not_mutate_an_existing_
        # configuration_record`).
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="fast_lookback",
                    label="Fast EMA Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=12,
                    minimum=1,
                    maximum=200,
                    help_text="Period of the fast (short) EMA.",
                ),
                ParameterDefinition(
                    parameter_id="slow_lookback",
                    label="Slow EMA Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=26,
                    minimum=2,
                    maximum=400,
                    help_text="Period of the slow (long) EMA. Must exceed fast_lookback.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        fast = require_int(config.values, "fast_lookback")
        slow = require_int(config.values, "slow_lookback")
        return (f"ema_{fast}", f"ema_{slow}")

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        fast_name, slow_name = self.required_features(config)
        fast = feature_values.get(fast_name)
        slow = feature_values.get(slow_name)
        if fast is None or slow is None:
            return None

        price = bar.close
        if fast.value > slow.value and price > fast.value:
            direction = StrategyDirection.BULLISH
        elif fast.value < slow.value and price < fast.value:
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
            evidence=(fast, slow),
        )
