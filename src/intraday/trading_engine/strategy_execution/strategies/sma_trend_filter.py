# File: src/intraday/trading_engine/strategy_execution/strategies/sma_trend_filter.py
#
# Checkpoint 26: SMA Trend Filter - price-vs-single-SMA shape, distinct
# from the crossover shape of EmaCrossoverStrategy.
#
# Checkpoint 65.10: FIRST Market Context consumption by a live-eligible
# strategy. Before this checkpoint the strategy declared a raw `sma_N`
# dependency and computed `(price - sma) / sma` (expressed as a
# `band = sma * band_percent / 100` comparison) INLINE. That inline
# computation is exactly the canonical `price_vs_ma_pct_sma` formula
# (`signal_intelligence.feature_engine.price_vs_ma_pct` -
# `(close - ma) / ma`, a signed fraction). Per the 65.09 audit
# recommendation and the 65.10 directive Part B/C ("prefer declaring
# price_vs_ma_pct_sma as a dependency rather than recalculating MA
# distance inside the strategy" / "do NOT recalculate the feature
# inside the strategy"), the strategy now declares
# `price_vs_ma_pct_sma_{lookback}` as its ONLY feature dependency and
# reads the ratio directly from that canonical `FeatureValue`, instead
# of computing it locally from a raw `sma_{lookback}` value.
#
# Strategy role of price_vs_ma_pct_sma: REQUIRED CONDITION - it does not
# sit alongside the existing band-threshold decision as extra
# confirmation/filtering, it IS that decision. The threshold comparison
# (`abs(ratio) >= band_percent/100`) and the resulting BULLISH/
# BEARISH/NEUTRAL/`band_percent` semantics are UNCHANGED bit-for-bit -
# only the source of the ratio moved from local arithmetic to the
# canonical feature. This is the only role consistent with the
# strategy's own documented intent (see class docstring below): the
# strategy's entire purpose already WAS "how far is price from its SMA,
# in percent", which is precisely what price_vs_ma_pct_sma computes. No
# new trading semantics were invented - see taskReport.md Part D.
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
    different in shape from the two-EMA crossover strategy.

    Checkpoint 65.10: the "how far is price from its SMA" distance is
    now sourced from the canonical `price_vs_ma_pct_sma` Market Context
    feature rather than computed inline from a raw SMA value. Signal
    identity (BULLISH/BEARISH/NEUTRAL thresholds, `band_percent`
    semantics) is unchanged."""

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
                    default=30,
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
                    # with zero guidance. Checkpoint 64.17 §13: 0.75% is
                    # now the CONSERVATIVE BASELINE research starting
                    # point for this asset class (a research starting
                    # point, not a claim of optimal profitability - see
                    # docs/research/STRATEGY_DEFAULT_PROFILES.md); the
                    # frontend both pre-fills this AND shows it as the
                    # field's placeholder hint - see
                    # `ParameterSchemaFields.tsx`. `default` is JSON-
                    # serialized verbatim by the API (`strategy_
                    # configuration_views.py`), so it must stay a plain
                    # float here, never a `Decimal` (same JSON-boundary
                    # class of bug as `coerce_configuration_values`).
                    default=0.75,
                    minimum=0,
                    maximum=10,
                    help_text="Percent distance from SMA required before a direction is declared. "
                    "Suggested starting value: 0.75%.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        lookback = require_int(config.values, "lookback")
        # Checkpoint 65.10: canonical Market Context feature dependency,
        # replacing the previous raw `sma_{lookback}` dependency. See
        # module docstring for why this is a substitution, not an
        # addition, and taskReport.md for the full 65.10 rationale.
        return (f"price_vs_ma_pct_sma_{lookback}",)

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        (price_vs_ma_pct_name,) = self.required_features(config)
        price_vs_ma_pct = feature_values.get(price_vs_ma_pct_name)
        # Checkpoint 65.10 Part H (missing context): unchanged contract -
        # this strategy has ALWAYS returned None when its single required
        # feature is unavailable (warm-up incomplete, feature not
        # computed, etc.) - see the pre-65.10 `sma is None` check this
        # replaces. No new "neutral"/0 default is invented for
        # price_vs_ma_pct_sma; unavailable context means no signal, same
        # as unavailable sma did before.
        if price_vs_ma_pct is None:
            return None

        band_percent = require_decimal(config.values, "band_percent")
        price = bar.close
        # `price_vs_ma_pct_sma` is a SIGNED FRACTION (e.g. 0.02 == price
        # 2% above the SMA - see price_vs_ma_pct.py module docstring),
        # while `band_percent` is configured as a percent (e.g. 0.75 ==
        # 0.75%), matching its pre-existing configuration convention
        # (`ParameterSchemaFields.tsx`, `default=0.75`, "Percent distance
        # from SMA"). Dividing by 100 converts the configured percent
        # into the same fraction units as the feature - this is a UNIT
        # CONVERSION only, mathematically identical to the pre-65.10
        # `band = sma.value * band_percent / 100` comparison against
        # `price - sma.value`.
        band_fraction = band_percent / 100
        ratio = price_vs_ma_pct.value

        if ratio > band_fraction:
            direction = StrategyDirection.BULLISH
        elif ratio < -band_fraction:
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
            # Checkpoint 65.10 Part K: evidence carries the canonical
            # feature's own `FeatureValue` verbatim (feature_name,
            # feature_version, instrument_id, timeframe, timestamp,
            # value) - never reconstructed after the fact.
            evidence=(price_vs_ma_pct,),
        )
