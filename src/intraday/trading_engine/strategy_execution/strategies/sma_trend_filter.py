# File: src/intraday/trading_engine/strategy_execution/strategies/sma_trend_filter.py
#
# Checkpoint 26: SMA Trend Filter - price-vs-single-SMA shape, distinct
# from the crossover shape of EmaCrossoverStrategy. Uses only
# `signal_intelligence.feature_engine.sma` (existing, tested).
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

STRATEGY_ID = "sma_trend_filter"
DISPLAY_NAME = "SMA Trend Filter"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"


class SmaTrendFilterStrategy:
    """BULLISH when close is above SMA by at least `band_percent`;
    BEARISH when close is below SMA by at least `band_percent`; NEUTRAL
    within the band. A single-feature-vs-price comparison, deliberately
    different in shape from the two-EMA crossover strategy."""

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
                    label="SMA Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=20,
                    minimum=1,
                    maximum=400,
                    help_text="Period of the trend-filter SMA.",
                ),
                ParameterDefinition(
                    parameter_id="band_percent",
                    label="Neutral Band (%)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    # A REAL bug found from a live report: this field had
                    # `default=None`, so every user had to guess a value
                    # with zero guidance (the reporting user's own guess,
                    # 0.02%, is far too tight for NSE cash-equity intraday
                    # noise and would fire on almost every bar). 0.2%
                    # is a reasonable starting neutral band for this
                    # asset class; the frontend now both pre-fills this
                    # AND shows it as the field's placeholder hint - see
                    # `ParameterSchemaFields.tsx`. `default` is JSON-
                    # serialized verbatim by the API (`strategy_
                    # configuration_views.py`), so it must stay a plain
                    # float here, never a `Decimal` (same JSON-boundary
                    # class of bug as `coerce_configuration_values`).
                    default=0.2,
                    minimum=0,
                    maximum=10,
                    help_text="Percent distance from SMA required before a direction is declared. "
                    "Suggested starting value: 0.2%.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        lookback = require_int(config.values, "lookback")
        return (f"sma_{lookback}",)

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        (sma_name,) = self.required_features(config)
        sma = feature_values.get(sma_name)
        if sma is None:
            return None

        band_percent = require_decimal(config.values, "band_percent")
        price = bar.close
        band = sma.value * band_percent / 100

        if price > sma.value + band:
            direction = StrategyDirection.BULLISH
        elif price < sma.value - band:
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
            evidence=(sma,),
        )
