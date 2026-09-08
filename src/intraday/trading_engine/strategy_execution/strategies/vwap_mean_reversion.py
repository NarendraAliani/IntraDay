# File: src/intraday/trading_engine/strategy_execution/strategies/vwap_mean_reversion.py
#
# CHECKPOINT-VWAP-B: VWAP Mean-Reversion - Phase B of
# `VWAP_STRATEGY_ROADMAP.md`. A genuinely NEW strategy, unrelated to and
# not touching any other strategy in this directory (a different,
# multi-condition-scorer strategy remains paused per `CHECKPOINT_75`'s
# explicit resumption criterion). Deliberately small: 4 parameters, one
# directly falsifiable hypothesis ("price mean-reverts to session VWAP
# once it deviates by N×ATR"), no multi-condition scorer. `registry.py`
# NOT touched - still unregistered, unreachable from the live
# scanner/backtest API.
#
# ---------------------------------------------------------------------------
# DESIGN - explicit
# ---------------------------------------------------------------------------
#
# Entry (mean-reversion): uses `vwap` (CHECKPOINT-VWAP-A,
# `signal_intelligence.feature_engine.vwap`) and `atr_{atr_lookback}`
# (existing, unmodified `atr.py`).
#
#     deviation_band = N * ATR         (N = vwap_deviation_atr_multiplier)
#
#     BULLISH  when  close < vwap - deviation_band   (price fell below
#                    VWAP by >= N×ATR - expect reversion UP)
#     BEARISH  when  close > vwap + deviation_band   (price rose above
#                    VWAP by >= N×ATR - expect reversion DOWN)
#     NEUTRAL  otherwise (price is within the deviation band, or a
#               required feature is not yet available - warmup)
#
# Exit (single target, deliberately NOT a T1/T2/T3 ladder - see
# `VWAP_STRATEGY_ROADMAP.md` §3's own reasoning, restated in
# `build_trade_plan()`'s own docstring below):
#
#     target = entry + target_reversion_fraction * (vwap - entry)
#
# Direction-agnostic by construction: `(vwap - entry)` is POSITIVE for a
# BULLISH entry (entry is below vwap) and NEGATIVE for a BEARISH entry
# (entry is above vwap), so the SAME formula produces a target above
# entry for a long and below entry for a short, with no separate
# sign-branch needed. `target_reversion_fraction = 1.0` -> target ==
# vwap exactly; a smaller fraction targets a PARTIAL reversion closer
# to entry.
#
#     stop_loss = entry - sign * stop_loss_atr_multiplier * ATR
#                 (sign = +1 BULLISH, -1 BEARISH)
#
# ---------------------------------------------------------------------------
# The M > N cross-parameter constraint - HONEST FINDING, not a
# workaround
# ---------------------------------------------------------------------------
#
# `stop_loss_atr_multiplier` (M) must exceed `vwap_deviation_atr_
# multiplier` (N) for the stop to sit WIDER than the deviation band the
# entry itself already required price to cross - otherwise the stop
# would sit at or inside the entry's own trigger distance, a degenerate
# plan. `ParameterDefinition` (`trading_engine.strategy_execution.
# contracts`) was checked directly before deciding how to handle this:
# it carries only PER-PARAMETER static `minimum`/`maximum` bounds
# (`Decimal | int | None`) - there is NO mechanism to express "this
# parameter's valid range depends on another parameter's actual
# configured value". This is confirmed the SAME situation
# `ema_crossover.py`'s own `slow_lookback` ("Must exceed fast_lookback")
# and `atr_volatility_breakout.py`'s target_1 < target_2 < target_3
# ladder are already in: BOTH are enforced ONLY by `help_text`
# documentation, never by schema or runtime validation anywhere in this
# codebase today. This is a genuine, pre-existing gap in what the
# `ParameterDefinition` schema can express - reported honestly here,
# not silently worked around with an undocumented convention.
#
# UNLIKE those two precedents, this strategy adds one small, EXPLICIT,
# TESTED runtime guard in `build_trade_plan()` (not in the schema, not
# a silent convention): if `M <= N`, `build_trade_plan()` returns
# `None` rather than emitting a degenerate plan - the SAME "never
# fabricate a plan from bad inputs" discipline `atr_volatility_
# breakout.py`'s own `build_trade_plan()` already uses for missing ATR.
# This is a genuine, additive design decision for THIS strategy, not a
# schema-level fix and not retroactively applied to `ema_crossover`/
# `atr_volatility_breakout` (out of this checkpoint's scope).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Version
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

STRATEGY_ID = "vwap_mean_reversion"
DISPLAY_NAME = "VWAP Mean Reversion"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"

_EVIDENCE_VERSION = Version(value="v1")
DEVIATION_MULTIPLE_FEATURE_NAME = "vwap_deviation_atr_multiple"
"""Evidence-only field name (not a registered `field_registry.py`
canonical feature - this is a per-signal COMPUTED value, not read from
`feature_values`). Signed: positive = price above VWAP, negative =
price below VWAP - matching `price_delta.py`'s own signed-value
precedent over a two-column shape."""
TARGET_PRICE_FEATURE_NAME = "vwap_implied_target_price"
STOP_PRICE_FEATURE_NAME = "vwap_implied_stop_price"
"""Both evidence-only, TradePlan-preview values attached directly to
the SIGNAL (not only inside the separate `TradePlan` object) so a human
auditing one signal can see the implied trade's risk/reward without
also having to inspect `build_trade_plan()`'s own separate output -
only attached for a genuine BULLISH/BEARISH signal (undefined for
NEUTRAL, never fabricated)."""


class VwapMeanReversionStrategy:
    """BULLISH when price has fallen at least `vwap_deviation_atr_
    multiplier` x ATR below the session VWAP (expecting reversion up);
    BEARISH when price has risen at least that far above VWAP
    (expecting reversion down); NEUTRAL otherwise, including warmup
    (missing `vwap`/`atr_{lookback}`). See module docstring for the
    full design rationale, including the honest M > N cross-parameter
    finding."""

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="vwap_deviation_atr_multiplier",
                    label="VWAP Deviation Trigger (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.5"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("10"),
                    help_text="Entry triggers once price deviates from session VWAP by at "
                    "least this many multiples of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="stop_loss_atr_multiplier",
                    label="Stop Loss (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("2.5"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("15"),
                    help_text="Stop loss distance from entry, as a multiple of ATR. Must "
                    "exceed vwap_deviation_atr_multiplier (not enforced by this schema - "
                    "see module docstring; build_trade_plan() refuses to produce a plan "
                    "when this is violated).",
                ),
                ParameterDefinition(
                    parameter_id="atr_lookback",
                    label="ATR Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Period of the ATR used for both the deviation trigger and "
                    "the stop-loss distance.",
                ),
                ParameterDefinition(
                    parameter_id="target_reversion_fraction",
                    label="Target Reversion Fraction",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.0"),
                    minimum=Decimal("0.01"),
                    maximum=Decimal("1.0"),
                    help_text="Fraction of the entry-to-VWAP distance the target requires "
                    "reverting. 1.0 = target is VWAP itself; less than 1.0 = a partial "
                    "reversion target closer to entry.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        atr_lookback = require_int(config.values, "atr_lookback")
        return ("vwap", f"atr_{atr_lookback}")

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        vwap_name, atr_name = self.required_features(config)
        vwap = feature_values.get(vwap_name)
        atr = feature_values.get(atr_name)
        if vwap is None or atr is None:
            return None

        deviation_n = require_decimal(config.values, "vwap_deviation_atr_multiplier")
        price = bar.close
        deviation_band = deviation_n * atr.value

        if price < vwap.value - deviation_band:
            direction = StrategyDirection.BULLISH
        elif price > vwap.value + deviation_band:
            direction = StrategyDirection.BEARISH
        else:
            direction = StrategyDirection.NEUTRAL

        deviation_multiple = (
            (price - vwap.value) / atr.value if atr.value != 0 else Decimal(0)
        )
        deviation_evidence = FeatureValue(
            feature_name=DEVIATION_MULTIPLE_FEATURE_NAME,
            feature_version=_EVIDENCE_VERSION,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            value=deviation_multiple,
        )
        evidence: tuple[FeatureValue, ...] = (vwap, atr, deviation_evidence)

        if direction is not StrategyDirection.NEUTRAL:
            fraction = require_decimal(config.values, "target_reversion_fraction")
            stop_multiplier = require_decimal(config.values, "stop_loss_atr_multiplier")
            sign = Decimal(1) if direction is StrategyDirection.BULLISH else Decimal(-1)
            target_price = price + fraction * (vwap.value - price)
            stop_price = price - sign * stop_multiplier * atr.value
            evidence += (
                FeatureValue(
                    feature_name=TARGET_PRICE_FEATURE_NAME,
                    feature_version=_EVIDENCE_VERSION,
                    instrument_id=bar.instrument_id,
                    timeframe=bar.timeframe,
                    timestamp=bar.timestamp,
                    value=target_price,
                ),
                FeatureValue(
                    feature_name=STOP_PRICE_FEATURE_NAME,
                    feature_version=_EVIDENCE_VERSION,
                    instrument_id=bar.instrument_id,
                    timeframe=bar.timeframe,
                    timestamp=bar.timestamp,
                    value=stop_price,
                ),
            )

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
            evidence=evidence,
        )

    def build_trade_plan(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
        signal: StrategySignal,
    ) -> TradePlan | None:
        """SINGLE target only - deliberately NOT a T1/T2/T3 ladder, per
        `VWAP_STRATEGY_ROADMAP.md` §3's own design reasoning: the target
        (a fraction of the way back to VWAP) scales with the SAME
        distance the entry condition already proved price could travel
        (the deviation band), unlike an independently-chosen multiple
        further than what price typically reaches (`CHECKPOINT_75`'s
        own MFE finding, from an unrelated strategy's diagnosis). One
        target avoids that specific structural trap by construction,
        not by having a smaller number.

        Returns `None` for NEUTRAL, for missing ATR, AND for the
        `stop_loss_atr_multiplier <= vwap_deviation_atr_multiplier`
        degenerate case (see module docstring's "M > N" section) -
        never fabricates a plan from a nonsensical parameter
        combination, matching `atr_volatility_breakout.py`'s own
        "never fabricate a plan from missing data" discipline extended
        to bad parameter combinations too."""
        if signal.direction is StrategyDirection.NEUTRAL:
            return None

        atr_lookback = require_int(config.values, "atr_lookback")
        atr = feature_values.get(f"atr_{atr_lookback}")
        if atr is None:
            return None

        deviation_n = require_decimal(config.values, "vwap_deviation_atr_multiplier")
        stop_multiplier = require_decimal(config.values, "stop_loss_atr_multiplier")
        if stop_multiplier <= deviation_n:
            return None

        vwap = feature_values.get("vwap")
        if vwap is None:
            return None

        fraction = require_decimal(config.values, "target_reversion_fraction")
        entry = signal.price
        atr_value = atr.value
        sign = Decimal(1) if signal.direction is StrategyDirection.BULLISH else Decimal(-1)

        target = entry + fraction * (vwap.value - entry)
        stop_loss = entry - sign * stop_multiplier * atr_value

        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=datetime.now(UTC),
            calculation_method=(
                "VWAP mean-reversion, single target: "
                f"entry=signal-time close ({entry}), an ENTRY CANDIDATE/REFERENCE PRICE "
                "ONLY (actual backtest fill remains next-bar-open, unchanged); "
                f"vwap={vwap.value} at signal time; "
                f"target=entry+{fraction}*(vwap-entry)={target}; "
                f"stop_loss=entry-{sign}*{stop_multiplier}xATR({atr_lookback})={stop_loss}. "
                f"ATR={atr_value} at signal time. No target_2/target_3 (single-target "
                "design - see module docstring)."
            ),
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target,
        )
