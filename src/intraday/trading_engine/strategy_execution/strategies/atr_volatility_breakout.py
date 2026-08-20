# File: src/intraday/trading_engine/strategy_execution/strategies/atr_volatility_breakout.py
#
# Checkpoint 26: ATR Volatility Breakout - volatility-threshold shape,
# distinct from both the crossover and trend-filter strategies. Uses
# only `signal_intelligence.feature_engine.atr` (existing, tested).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.trading_engine.strategy_execution.contracts import (
    ParameterDefinition,
    ParameterType,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyParameterSchema,
    StrategySignal,
    TradePlan,
    require_decimal,
    require_int,
)
from intraday.trading_engine.strategy_execution.errors import InvalidParameterValueError

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
                    # Checkpoint 64.17 §13: was `None` (no guidance at
                    # all) - 2.0 is now the CONSERVATIVE BASELINE
                    # research starting point (a research starting point,
                    # not a claim of optimal profitability - see
                    # docs/research/STRATEGY_DEFAULT_PROFILES.md).
                    default=2.0,
                    minimum=0,
                    maximum=10,
                    help_text="Breakout threshold as a multiple of ATR. "
                    "Suggested starting value: 2.0.",
                ),
                # Checkpoint 64.7: the TradePlan calculation's own
                # configurable multipliers - every value `build_trade_plan()`
                # produces is `entry +/- {this} * ATR`, never a hardcoded
                # constant. Defaults are a conventional ascending
                # risk:reward ladder (1R/1.5R/2.5R/4R stop:targets), but an
                # operator can retune them per-instrument via the existing
                # strategy configuration mechanism - no code change needed.
                ParameterDefinition(
                    parameter_id="stop_loss_atr_multiplier",
                    label="Stop Loss (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=1.0,
                    minimum=Decimal("0.1"),
                    maximum=10,
                    help_text="Stop loss distance from entry, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="target_1_atr_multiplier",
                    label="Target 1 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=1.5,
                    minimum=Decimal("0.1"),
                    maximum=20,
                    help_text="Target 1 distance from entry, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="target_2_atr_multiplier",
                    label="Target 2 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=2.5,
                    minimum=Decimal("0.1"),
                    maximum=20,
                    help_text="Target 2 distance from entry, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="target_3_atr_multiplier",
                    label="Target 3 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    # Checkpoint 64.17 §13: conservative baseline 3.5
                    # (was 4.0) - a research starting point, not a claim
                    # of optimal profitability.
                    default=3.5,
                    minimum=Decimal("0.1"),
                    maximum=20,
                    help_text="Target 3 distance from entry, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="trailing_stop_atr_multiplier",
                    label="Trailing Stop (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=1.0,
                    minimum=Decimal("0.1"),
                    maximum=10,
                    help_text="Trailing stop distance from price, as a multiple of ATR.",
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

    def build_trade_plan(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
        signal: StrategySignal,
    ) -> TradePlan | None:
        """Checkpoint 64.7 §4: the ONE strategy in this codebase that
        produces a real `TradePlan` - chosen because it already computes
        ATR for its own directional threshold (never a second,
        redundant ATR computation), so a volatility-scaled entry/stop/
        target ladder is a defensible extension of logic this strategy
        already has, not a bolted-on fabrication. Returns `None` for a
        NEUTRAL signal (no trade is being proposed) - a directional-only
        result never gets a plan, matching `ema_crossover`'s own
        contract of "not every signal has a plan"."""
        if signal.direction is StrategyDirection.NEUTRAL:
            return None

        (atr_name,) = self.required_features(config)
        atr = feature_values.get(atr_name)
        if atr is None:
            return None

        # A plan is an OPTIONAL capability - a caller supplying a
        # minimal config (e.g. only `atr_multiplier`, sufficient for
        # `evaluate()`'s own directional threshold) without the newer
        # plan-only multipliers simply gets no plan, never a fabricated
        # one and never an exception that would break signal generation
        # itself (evaluate() has already succeeded by the time this
        # runs).
        try:
            stop_multiplier = require_decimal(config.values, "stop_loss_atr_multiplier")
            target_1_multiplier = require_decimal(config.values, "target_1_atr_multiplier")
            target_2_multiplier = require_decimal(config.values, "target_2_atr_multiplier")
            target_3_multiplier = require_decimal(config.values, "target_3_atr_multiplier")
            trailing_multiplier = require_decimal(config.values, "trailing_stop_atr_multiplier")
        except (KeyError, InvalidParameterValueError):
            return None

        entry = signal.price
        atr_value = atr.value
        sign = 1 if signal.direction is StrategyDirection.BULLISH else -1

        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=datetime.now(UTC),
            calculation_method=(
                f"ATR({config.values.get('lookback')}) volatility-based: "
                f"entry=breakout close ({entry}); "
                f"stop_loss=entry-{sign}*{stop_multiplier}xATR; "
                f"target_1..3=entry+{sign}*[{target_1_multiplier},{target_2_multiplier},"
                f"{target_3_multiplier}]xATR; "
                f"trailing_stop=entry-{sign}*{trailing_multiplier}xATR (initial level, moves "
                f"with price - this is the INITIAL value only). ATR={atr_value} at signal time."
            ),
            entry_price=entry,
            stop_loss=entry - sign * stop_multiplier * atr_value,
            target_1=entry + sign * target_1_multiplier * atr_value,
            target_2=entry + sign * target_2_multiplier * atr_value,
            target_3=entry + sign * target_3_multiplier * atr_value,
            trailing_stop_loss=entry - sign * trailing_multiplier * atr_value,
        )
