# File: src/intraday/trading_engine/strategy_execution/strategies/orb_breakout.py
#
# CHECKPOINT-ORB-B: Opening Range Breakout - Phase B of
# `ORB_STRATEGY_ROADMAP.md`. A genuinely NEW strategy, a third design
# family unrelated to the paused multi-condition scorer and the
# already-validated (still paused for tuning) mean-reversion strategy
# - deliberately small: 5 parameters, one directly falsifiable
# hypothesis ("price breaking beyond the first N minutes' range
# continues in that direction"), no multi-rung target ladder.
# `registry.py` NOT touched - still unregistered, unreachable from the
# live scanner/backtest API.
#
# ---------------------------------------------------------------------------
# DESIGN - explicit
# ---------------------------------------------------------------------------
#
# Uses `opening_range_high`/`opening_range_low` (CHECKPOINT-ORB-A,
# `signal_intelligence.feature_engine.opening_range`) - two parallel,
# frozen-once-the-window-closes fields.
#
#     BULLISH  when  close > opening_range_high
#     BEARISH  when  close < opening_range_low
#     NEUTRAL  otherwise (inside the range, before the window closes,
#              or filtered out - see below)
#
# Exit (single target, deliberately NOT a ladder - the SAME lesson
# `ORB_STRATEGY_ROADMAP.md` §3 already applied up front, restated in
# `build_trade_plan()`'s own docstring):
#
#     range_size = opening_range_high - opening_range_low
#     target = entry + sign * target_range_multiplier * range_size
#     stop   = opposite range boundary (stop_range_fraction=1.0) or a
#              tighter point INSIDE the range (stop_range_fraction<1.0):
#                BULLISH: stop = opening_range_high - stop_range_fraction * range_size
#                BEARISH: stop = opening_range_low  + stop_range_fraction * range_size
#              (fraction=1.0 reduces exactly to the opposite boundary
#              itself: range_high - 1.0*range_size = range_high -
#              (range_high-range_low) = range_low, the BULLISH case's
#              opposite boundary, and symmetrically for BEARISH.)
#
# NO CROSS-PARAMETER DEGENERATE CASE POSSIBLE, unlike
# `vwap_mean_reversion.py`'s own M > N guard - a structural property of
# this design, not a runtime check needed here: since entry only ever
# fires when `close` is already strictly beyond the range boundary
# (`close > opening_range_high` for BULLISH), and `stop = opening_range_
# high - stop_range_fraction * range_size < opening_range_high < entry`
# for any `stop_range_fraction > 0`, the stop is ALWAYS below entry for
# a BULLISH breakout (symmetrically above for BEARISH) by construction
# - there is no parameter combination that produces a stop on the wrong
# side of entry.
#
# ---------------------------------------------------------------------------
# `atr_lookback`'s role - DECIDED, not included by inertia
# ---------------------------------------------------------------------------
#
# `ORB_STRATEGY_ROADMAP.md` §2 explicitly left this open. DECISION:
# option (b) - ATR is included as an OPTIONAL, DEFAULT-DISABLED range-
# size FILTER (`minimum_range_atr_multiplier`, default `Decimal("0")`
# - a deliberate NO-OP default, the same "no-op default" convention a
# different, unrelated, paused strategy elsewhere in this codebase
# already established for its own quality-score gate). REASONING: a
# very narrow opening range on a quiet
# day can produce a "breakout" that is really just ordinary
# chop crossing a tiny threshold - not a meaningfully different market
# condition from any other 2-tick move. Requiring the range's own size
# to exceed some ATR-relative minimum before a breakout is even
# considered is a real, well-motivated filter for that specific noise
# case - but it is NOT part of ORB's own core hypothesis (which is
# about breaking a SESSION-relative range, not about volatility
# per se), so it defaults OFF (`minimum_range_atr_multiplier=0`, which
# always passes: `range_size >= 0 * atr` is true for any non-negative
# range_size) rather than being force-enabled. When the filter is
# disabled (the default), `atr_{atr_lookback}` is NOT even added to
# `required_features()` - a configuration that never uses the filter
# never needs ATR to warm up at all, matching this project's own
# "never require a feature a configuration doesn't actually use"
# discipline.
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

STRATEGY_ID = "orb_breakout"
DISPLAY_NAME = "Opening Range Breakout"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"

_EVIDENCE_VERSION = Version(value="v1")
RANGE_SIZE_FEATURE_NAME = "orb_range_size"
BREAKOUT_DISTANCE_FEATURE_NAME = "orb_breakout_distance_range_multiple"
TARGET_PRICE_FEATURE_NAME = "orb_implied_target_price"
STOP_PRICE_FEATURE_NAME = "orb_implied_stop_price"
"""Evidence-only field names (not registered `field_registry.py`
canonical features - per-signal COMPUTED values, the same pattern
`vwap_mean_reversion.py`'s own `DEVIATION_MULTIPLE_FEATURE_NAME`/
`TARGET_PRICE_FEATURE_NAME`/`STOP_PRICE_FEATURE_NAME` already
establish). `BREAKOUT_DISTANCE...` is signed: positive = price beyond
the range in the breakout's own direction, in range-size units (e.g.
`0.5` = price is half a range-width beyond the boundary it broke)."""


class OrbBreakoutStrategy:
    """BULLISH when price closes above the session's opening-range
    high; BEARISH when it closes below the opening-range low; NEUTRAL
    otherwise (inside the range, before the window closes, or filtered
    out by `minimum_range_atr_multiplier` - see module docstring for
    the full design rationale, including the `atr_lookback` decision)."""

    strategy_id = STRATEGY_ID
    display_name = DISPLAY_NAME
    specification_version = SPECIFICATION_VERSION
    code_version = CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="opening_range_minutes",
                    label="Opening Range Window (minutes)",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=15,
                    minimum=1,
                    maximum=120,
                    help_text="Duration of the opening range window from session market_open. "
                    "Classic convention: 15.",
                ),
                ParameterDefinition(
                    parameter_id="target_range_multiplier",
                    label="Target (x Range Size)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.0"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("10"),
                    help_text="Target distance beyond entry, as a multiple of the opening "
                    "range's own size.",
                ),
                ParameterDefinition(
                    parameter_id="stop_range_fraction",
                    label="Stop (fraction of Range Size)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("1.0"),
                    minimum=Decimal("0.01"),
                    maximum=Decimal("1.0"),
                    help_text="Stop distance from the range boundary the price broke through, "
                    "as a fraction of the range's own size. 1.0 = the opposite range "
                    "boundary itself; less than 1.0 = a tighter stop inside the range.",
                ),
                ParameterDefinition(
                    parameter_id="minimum_range_atr_multiplier",
                    label="Minimum Range Size (x ATR) - 0 disables",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("0"),
                    minimum=Decimal("0"),
                    maximum=Decimal("10"),
                    help_text="Optional filter: the opening range's own size must be at least "
                    "this many multiples of ATR before a breakout is considered - "
                    "deliberately guards against trading a too-narrow, noise-prone range. "
                    "0 (the default) disables the filter entirely - every range size passes.",
                ),
                ParameterDefinition(
                    parameter_id="atr_lookback",
                    label="ATR Lookback (filter only)",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="ATR period used ONLY by the optional minimum-range-size filter "
                    "above - irrelevant, and not read at all, when that filter is disabled "
                    "(minimum_range_atr_multiplier=0).",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        n = require_int(config.values, "opening_range_minutes")
        features = (f"opening_range_high_{n}", f"opening_range_low_{n}")
        min_atr_multiplier = require_decimal(config.values, "minimum_range_atr_multiplier")
        if min_atr_multiplier > 0:
            atr_lookback = require_int(config.values, "atr_lookback")
            features += (f"atr_{atr_lookback}",)
        return features

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        n = require_int(config.values, "opening_range_minutes")
        range_high_fv = feature_values.get(f"opening_range_high_{n}")
        range_low_fv = feature_values.get(f"opening_range_low_{n}")
        if range_high_fv is None or range_low_fv is None:
            # Window not yet complete for this session, or warm-up -
            # never a fabricated value (CHECKPOINT-ORB-A's own
            # no-output convention for an incomplete window).
            return None

        range_high = range_high_fv.value
        range_low = range_low_fv.value
        range_size = range_high - range_low
        price = bar.close

        if price > range_high:
            raw_direction = StrategyDirection.BULLISH
        elif price < range_low:
            raw_direction = StrategyDirection.BEARISH
        else:
            raw_direction = StrategyDirection.NEUTRAL

        direction = raw_direction
        min_atr_multiplier = require_decimal(config.values, "minimum_range_atr_multiplier")
        if raw_direction is not StrategyDirection.NEUTRAL and min_atr_multiplier > 0:
            atr_lookback = require_int(config.values, "atr_lookback")
            atr = feature_values.get(f"atr_{atr_lookback}")
            if atr is None:
                # Filter is genuinely enabled but ATR hasn't warmed up
                # yet - honest warm-up, never a fabricated pass/fail.
                return None
            if range_size < min_atr_multiplier * atr.value:
                # Range too narrow relative to ATR - filtered out.
                direction = StrategyDirection.NEUTRAL

        evidence: tuple[FeatureValue, ...] = (range_high_fv, range_low_fv)
        if direction is not StrategyDirection.NEUTRAL and range_size != 0:
            breakout_distance = (
                (price - range_high) / range_size
                if direction is StrategyDirection.BULLISH
                else (range_low - price) / range_size
            )
            evidence += (
                FeatureValue(
                    feature_name=RANGE_SIZE_FEATURE_NAME,
                    feature_version=_EVIDENCE_VERSION,
                    instrument_id=bar.instrument_id,
                    timeframe=bar.timeframe,
                    timestamp=bar.timestamp,
                    value=range_size,
                ),
                FeatureValue(
                    feature_name=BREAKOUT_DISTANCE_FEATURE_NAME,
                    feature_version=_EVIDENCE_VERSION,
                    instrument_id=bar.instrument_id,
                    timeframe=bar.timeframe,
                    timestamp=bar.timestamp,
                    value=breakout_distance,
                ),
            )
            target_multiplier = require_decimal(config.values, "target_range_multiplier")
            stop_fraction = require_decimal(config.values, "stop_range_fraction")
            sign = Decimal(1) if direction is StrategyDirection.BULLISH else Decimal(-1)
            target_price = price + sign * target_multiplier * range_size
            stop_price = (
                range_high - stop_fraction * range_size
                if direction is StrategyDirection.BULLISH
                else range_low + stop_fraction * range_size
            )
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
        """SINGLE target only - deliberately NOT a ladder, per
        `ORB_STRATEGY_ROADMAP.md` §3's own up-front design decision:
        target/stop are both defined directly in terms of the opening
        range's OWN size (a quantity this specific day's own realized
        volatility already determined), not an independently-chosen
        multiple that price might rarely reach.

        No cross-parameter degenerate case is possible here (unlike
        `vwap_mean_reversion.py`'s own M > N guard) - see module
        docstring's own structural-safety note; no runtime refusal
        needed for that reason. Still returns `None` for NEUTRAL and
        for missing range data, matching every other strategy's own
        "never fabricate a plan from missing data" discipline."""
        if signal.direction is StrategyDirection.NEUTRAL:
            return None

        n = require_int(config.values, "opening_range_minutes")
        range_high_fv = feature_values.get(f"opening_range_high_{n}")
        range_low_fv = feature_values.get(f"opening_range_low_{n}")
        if range_high_fv is None or range_low_fv is None:
            return None

        range_high = range_high_fv.value
        range_low = range_low_fv.value
        range_size = range_high - range_low
        if range_size <= 0:
            # A zero/negative range is mathematically degenerate (would
            # require a target/stop identical to entry or worse) - never
            # fabricate a plan from it.
            return None

        entry = signal.price
        target_multiplier = require_decimal(config.values, "target_range_multiplier")
        stop_fraction = require_decimal(config.values, "stop_range_fraction")
        sign = Decimal(1) if signal.direction is StrategyDirection.BULLISH else Decimal(-1)

        target = entry + sign * target_multiplier * range_size
        stop_loss = (
            range_high - stop_fraction * range_size
            if signal.direction is StrategyDirection.BULLISH
            else range_low + stop_fraction * range_size
        )

        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=datetime.now(UTC),
            calculation_method=(
                "Opening range breakout, single target: "
                f"entry=signal-time close ({entry}), an ENTRY CANDIDATE/REFERENCE PRICE "
                "ONLY (actual backtest fill remains next-bar-open, unchanged); "
                f"opening_range=[{range_low}, {range_high}] (size={range_size}); "
                f"target=entry+{sign}*{target_multiplier}*range_size={target}; "
                f"stop_loss={stop_fraction}xrange_size from the broken boundary={stop_loss}. "
                "No target_2/target_3 (single-target design - see module docstring)."
            ),
            entry_price=entry,
            stop_loss=stop_loss,
            target_1=target,
        )
