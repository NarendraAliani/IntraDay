# File: src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py
#
# Checkpoint 64.50: GainzCompatibleResearchStrategy.
#
# HONESTY NOTICE (do not remove): this is NOT the Gainz strategy, and its
# signal logic is NOT verified GainzAlgo V2 mathematics. No Gainz
# reference source file exists anywhere in this repository (independently
# re-verified across checkpoints 64.44/46/47/48/49). This strategy exists
# to prove one thing: that a REAL strategy, using the existing
# `Strategy` protocol/`required_features()`/`StrategyExecutionCoordinator`/
# `StrategySignal`/`TradePlan`/`StrategyRegistry` architecture, can
# consume the 64.49 canonical feature set (RSI, ADX, +DI, -DI, Relative
# Volume, MACD Histogram, Candle Body Ratio) end-to-end with NO
# strategy-specific indicator framework and NO indicator math computed
# inside the strategy itself.
#
# Its bullish/bearish conditions below are a CANONICAL FEATURE-CONSUMPTION
# RESEARCH PROFILE -- a deliberately simple, fully-configurable rule set
# chosen only to exercise all 7 new features together. They are NOT
# claimed to be "the Gainz formula". A future, real Gainz implementation
# (if a reference source is ever supplied) may reuse these SAME canonical
# features but would almost certainly need different combination logic --
# this strategy does not attempt to guess that logic.
#
# All thresholds are configurable via the existing
# `ParameterDefinition`/`StrategyConfigurationValues` mechanism (Checkpoint
# 26) -- nothing is hard-coded. Defaults below are CONSERVATIVE RESEARCH
# DEFAULTS for paper/backtest research, not claimed-optimal Gainz values
# (matching the "conservative baseline" precedent `ema_crossover.py` and
# `atr_volatility_breakout.py` already established at Checkpoint 64.17 §13).
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

STRATEGY_ID = "gainz_compatible_research"
DISPLAY_NAME = "Gainz-Compatible Research Strategy (Canonical Feature Consumption Profile)"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"


class GainzCompatibleResearchStrategy:
    """Consumes RSI, ADX, +DI, -DI, Relative Volume, MACD Histogram, and
    Candle Body Ratio -- all computed by the existing canonical feature
    registry/coordinator (Checkpoint 64.49), never by this class -- to
    produce a BULLISH/BEARISH/NEUTRAL `StrategySignal`.

    BULLISH when ALL of:
        RSI            >= rsi_bullish_threshold
        ADX            >= adx_minimum
        +DI            >  -DI
        Relative Volume>= relative_volume_minimum
        MACD Histogram >  0
        Candle Body Ratio >= candle_body_ratio_minimum

    BEARISH when ALL of:
        RSI            <= rsi_bearish_threshold
        ADX            >= adx_minimum
        -DI            >  +DI
        Relative Volume>= relative_volume_minimum
        MACD Histogram <  0
        Candle Body Ratio >= candle_body_ratio_minimum

    NEUTRAL otherwise, and also whenever ANY required feature is
    unavailable (insufficient warmup or a skipped/missing bar) -- this
    strategy NEVER fabricates a missing feature value; see `evaluate()`.

    THIS IS A RESEARCH/COMPATIBILITY RULE SET, NOT VERIFIED GAINZALGO V2
    SIGNAL MATHEMATICS. See module header.
    """

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="rsi_lookback",
                    label="RSI Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Wilder smoothing period N for RSI. "
                    "Conservative research default: 14.",
                ),
                ParameterDefinition(
                    parameter_id="rsi_bullish_threshold",
                    label="RSI Bullish Threshold",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("60"),
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                    help_text="RSI must be >= this for a BULLISH condition. "
                    "Conservative research default: 60.",
                ),
                ParameterDefinition(
                    parameter_id="rsi_bearish_threshold",
                    label="RSI Bearish Threshold",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("40"),
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                    help_text="RSI must be <= this for a BEARISH condition. "
                    "Conservative research default: 40.",
                ),
                ParameterDefinition(
                    parameter_id="adx_lookback",
                    label="ADX Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Wilder smoothing period N for ADX/+DI/-DI. "
                    "Conservative research default: 14.",
                ),
                ParameterDefinition(
                    parameter_id="adx_minimum",
                    label="ADX Minimum (trend strength gate)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("20"),
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                    help_text="ADX must be >= this for either directional condition. "
                    "Conservative research default: 20.",
                ),
                ParameterDefinition(
                    parameter_id="relative_volume_lookback",
                    label="Relative Volume Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=20,
                    minimum=1,
                    maximum=400,
                    help_text="Trailing-average window N for Relative Volume. "
                    "Conservative research default: 20.",
                ),
                ParameterDefinition(
                    parameter_id="relative_volume_minimum",
                    label="Relative Volume Minimum",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.0"),
                    minimum=Decimal("0"),
                    maximum=Decimal("50"),
                    help_text="Relative Volume must be >= this. "
                    "Conservative research default: 1.0 (at-or-above average volume).",
                ),
                ParameterDefinition(
                    parameter_id="macd_fast",
                    label="MACD Fast EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=12,
                    minimum=1,
                    maximum=200,
                    help_text="MACD fast EMA period. "
                    "Conservative research default: 12 (standard Appel).",
                ),
                ParameterDefinition(
                    parameter_id="macd_slow",
                    label="MACD Slow EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=26,
                    minimum=2,
                    maximum=400,
                    help_text="MACD slow EMA period. "
                    "Conservative research default: 26 (standard Appel).",
                ),
                ParameterDefinition(
                    parameter_id="macd_signal",
                    label="MACD Signal EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=9,
                    minimum=1,
                    maximum=200,
                    help_text="MACD signal-line EMA period. "
                    "Conservative research default: 9 (standard Appel).",
                ),
                ParameterDefinition(
                    parameter_id="candle_body_ratio_minimum",
                    label="Candle Body Ratio Minimum",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("0.5"),
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                    help_text="Candle Body Ratio must be >= this (conviction filter). "
                    "Conservative research default: 0.5.",
                ),
                # Checkpoint 64.50 Part 10: research-only, configurable
                # TradePlan multipliers, mirroring `atr_volatility_
                # breakout.py`'s own precedent -- NOT claimed to be actual
                # GainzAlgo V2 TP/SL mathematics, purely a conservative
                # research convenience reusing the existing ATR feature
                # this strategy does not otherwise require.
                ParameterDefinition(
                    parameter_id="trade_plan_atr_lookback",
                    label="TradePlan ATR Lookback (research SL/TP only)",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="ATR period used ONLY for research TradePlan SL/TP levels -- "
                    "not part of the BULLISH/BEARISH signal condition itself.",
                ),
                ParameterDefinition(
                    parameter_id="trade_plan_stop_loss_atr_multiplier",
                    label="TradePlan Stop Loss (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.0"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("10"),
                    help_text="Research-only stop-loss distance, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="trade_plan_target_1_atr_multiplier",
                    label="TradePlan Target 1 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.5"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("20"),
                    help_text="Research-only target-1 distance, as a multiple of ATR.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        rsi_lookback = require_int(config.values, "rsi_lookback")
        adx_lookback = require_int(config.values, "adx_lookback")
        rvol_lookback = require_int(config.values, "relative_volume_lookback")
        macd_fast = require_int(config.values, "macd_fast")
        macd_slow = require_int(config.values, "macd_slow")
        macd_signal = require_int(config.values, "macd_signal")
        return (
            f"rsi_{rsi_lookback}",
            f"adx_{adx_lookback}",
            f"plus_di_{adx_lookback}",
            f"minus_di_{adx_lookback}",
            f"relative_volume_{rvol_lookback}",
            f"macd_hist_{macd_fast}_{macd_slow}_{macd_signal}",
            "candle_body_ratio",
        )

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        (
            rsi_name,
            adx_name,
            plus_di_name,
            minus_di_name,
            rvol_name,
            macd_hist_name,
            body_ratio_name,
        ) = self.required_features(config)

        rsi = feature_values.get(rsi_name)
        adx = feature_values.get(adx_name)
        plus_di = feature_values.get(plus_di_name)
        minus_di = feature_values.get(minus_di_name)
        rvol = feature_values.get(rvol_name)
        macd_hist = feature_values.get(macd_hist_name)
        body_ratio = feature_values.get(body_ratio_name)

        # Checkpoint 64.50 Part 16: WARMUP / MISSING-DATA SAFETY. If ANY
        # required feature is unavailable (insufficient warmup, or a
        # skipped zero-baseline/zero-range bar upstream), this strategy
        # returns `None` -- it never fabricates a neutral/zero/default
        # value to paper over a missing feature, mirroring `Strategy.
        # evaluate()`'s own documented "never fabricate a signal for
        # missing data" contract.
        evidence = (rsi, adx, plus_di, minus_di, rvol, macd_hist, body_ratio)
        if any(f is None for f in evidence):
            return None
        assert rsi is not None  # narrow for mypy; already checked above
        assert adx is not None
        assert plus_di is not None
        assert minus_di is not None
        assert rvol is not None
        assert macd_hist is not None
        assert body_ratio is not None

        rsi_bullish_threshold = require_decimal(config.values, "rsi_bullish_threshold")
        rsi_bearish_threshold = require_decimal(config.values, "rsi_bearish_threshold")
        adx_minimum = require_decimal(config.values, "adx_minimum")
        rvol_minimum = require_decimal(config.values, "relative_volume_minimum")
        body_ratio_minimum = require_decimal(config.values, "candle_body_ratio_minimum")

        trend_strong_enough = adx.value >= adx_minimum
        volume_confirmed = rvol.value >= rvol_minimum
        conviction_confirmed = body_ratio.value >= body_ratio_minimum

        bullish = (
            rsi.value >= rsi_bullish_threshold
            and trend_strong_enough
            and plus_di.value > minus_di.value
            and volume_confirmed
            and macd_hist.value > 0
            and conviction_confirmed
        )
        bearish = (
            rsi.value <= rsi_bearish_threshold
            and trend_strong_enough
            and minus_di.value > plus_di.value
            and volume_confirmed
            and macd_hist.value < 0
            and conviction_confirmed
        )

        if bullish:
            direction = StrategyDirection.BULLISH
        elif bearish:
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
            evidence=evidence,  # type: ignore[arg-type]  # narrowed above; all non-None
        )

    def build_trade_plan(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
        signal: StrategySignal,
    ) -> TradePlan | None:
        """Research-only TradePlan, reusing the EXISTING `TradePlan`
        contract (no Gainz-specific TradePlan subtype). Uses ATR -- a feature this
        strategy does NOT request via `required_features()` for its own
        signal condition -- purely as a conservative research SL/TP
        convention, mirroring `atr_volatility_breakout.py`'s own
        precedent. Returns `None` for NEUTRAL (no trade proposed) or if
        ATR is unavailable (never fabricates a plan from missing data)."""
        if signal.direction is StrategyDirection.NEUTRAL:
            return None

        try:
            atr_lookback = require_int(config.values, "trade_plan_atr_lookback")
            stop_multiplier = require_decimal(config.values, "trade_plan_stop_loss_atr_multiplier")
            target_1_multiplier = require_decimal(
                config.values, "trade_plan_target_1_atr_multiplier"
            )
        except (KeyError, InvalidParameterValueError):
            return None

        atr = feature_values.get(f"atr_{atr_lookback}")
        if atr is None:
            # Advisory-only: this strategy does not itself request
            # `atr_{lookback}` via `required_features()`, so a caller
            # must have separately supplied it (e.g. via a coordinator
            # run that also computes it for another strategy) for a
            # research TradePlan to be produced here. Never fabricated.
            return None

        entry = signal.price
        atr_value = atr.value
        sign = 1 if signal.direction is StrategyDirection.BULLISH else -1

        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=datetime.now(UTC),
            calculation_method=(
                f"RESEARCH-ONLY (NOT verified GainzAlgo V2 TP/SL math): "
                f"entry=signal close ({entry}); "
                f"stop_loss=entry-{sign}*{stop_multiplier}xATR({atr_lookback}); "
                f"target_1=entry+{sign}*{target_1_multiplier}xATR({atr_lookback}). "
                f"ATR={atr_value} at signal time."
            ),
            entry_price=entry,
            stop_loss=entry - sign * stop_multiplier * atr_value,
            target_1=entry + sign * target_1_multiplier * atr_value,
        )
