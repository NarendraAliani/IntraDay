# File: src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py
#
# Checkpoint 64.99: GainzCompatibleResearchStrategy - profile "alpha".
#
# HONESTY NOTICE (do not remove): this is the "Gainz Research Adapter" /
# "Gainz-Compatible Research Strategy" - NOT authentic GainzAlgo, NOT
# verified Gainz V2, NOT a proprietary Gainz implementation. The
# read-only reference artifact at
# `docs/research/gainz_signal_engine_reference.py` is a third-party
# research/rebuild file, not authoritative Gainz source, and is NEVER
# imported/modified/called from here (see `.importlinter`/CI - this
# module has zero references to that path other than this comment).
#
# SCOPE (Checkpoint 64.99): exactly ONE strategy identity
# (`gainz_compatible_research`), exactly ONE profile (`alpha`). No
# Trend/Breakout/Mean Reversion/Hybrid/Scalp profile, no consensus
# (64.98's frozen DEFER decision). `profile` is a configuration ENUM
# parameter whose `allowed_values` contains ONLY "alpha" - the only
# value this class actually implements - so no unsupported profile can
# ever be selected (see `parameter_schema()` below).
#
# ALPHA CONDITION SOURCING: the reference file's `_score_row()` "alpha"
# profile branch is literally `pass` - Alpha relies entirely on the
# SHARED base scoring block above it in `_score_row()`. This adapter
# reimplements exactly that shared base block, condition-by-condition,
# using ONLY the existing canonical feature engine (never the
# reference's private `_ema`/`_rsi`/`_atr`/`_adx` functions, never its
# numeric weights as verified Gainz mathematics - see SCORING below).
#
# CONDITIONS IMPLEMENTED (shared-base block, canonical-feature-backed):
#   1. bullish_engulfing / bearish_engulfing  -> canonical `bullish_engulfing`
#      / `bearish_engulfing` features (64.97, EXACT MATCH per 64.98 audit).
#   2. stable_candle (body_ratio >= threshold) -> canonical `candle_body_ratio`
#      (64.97, EXACT MATCH per 64.98 audit).
#   3. RSI "not extremely exhausted" gate (rsi < threshold for bull,
#      rsi > 100-threshold for bear) -> canonical `rsi_{N}` (Wilder
#      convention - DIFFERS numerically from the reference's ewm-seeded
#      RSI by design; 64.98 accepted divergence, not reproduced here).
#   4. price_delta gate (price below/above an N-bar-ago reference)
#      -> canonical `price_delta_{N}` (64.97): `price_delta_N > 0` is the
#      reference's `price_up_delta`, `< 0` is `price_down_delta` - see
#      that feature's own module docstring for this exact equivalence.
#   5. Trend confirmation (close vs ema_trend, ema_fast vs ema_slow vs
#      ema_trend) -> canonical `ema_{N}` (three lookbacks) - DIFFERS
#      numerically from the reference's ewm-seeded EMA by design (64.98).
#   6. MACD Histogram sign -> canonical `macd_hist_{fast}_{slow}_{signal}`
#      - DIFFERS numerically from the reference by design (64.98).
#   7. Relative-volume + candle-direction confirmation -> canonical
#      `relative_volume_{N}` plus `bar.open`/`bar.close` (already
#      available on every `Bar`, no new feature needed) - DIFFERS
#      numerically from the reference's rolling-mean RVOL by design.
#   8. ADX-direction confirmation (adx >= minimum and +DI/-DI dominance)
#      -> canonical `adx_{N}`, `plus_di_{N}`, `minus_di_{N}` - DIFFERS
#      numerically from the reference by design (64.98).
#
# CONDITIONS DELIBERATELY OMITTED - DOCUMENTED BLOCKERS (never
# fabricated as substitute logic):
#
#   BLOCKER A - 20-bar breakout/breakdown (`breakout_bull`/
#   `breakout_bear` = close vs a 20-bar-prior rolling high/low). 64.98
#   classified `breakout` as REQUIRED BUT UNAVAILABLE: no canonical
#   `breakout`/rolling-high-low feature exists in the field registry as
#   of this checkpoint. This checkpoint does NOT implement a breakout
#   feature (explicitly out of scope per the directive) and does NOT
#   invent substitute breakout semantics inside this strategy. OMITTED.
#
#   BLOCKER B - RSI momentum (`momentum_bull`/`momentum_bear` = "RSI > 50
#   AND RSI is rising vs the PREVIOUS bar's RSI"). This requires the
#   PRIOR bar's RSI value. `Strategy.evaluate()`'s contract
#   (`strategy.py`) and `StrategyExecutionCoordinator.run()`
#   (`coordinator.py`) deliberately hand every strategy only the
#   CURRENT bar's `feature_values: dict[str, FeatureValue]` (one value
#   per field_id, at the latest bar only) - there is no
#   previous-bar-feature-value channel in the existing architecture, and
#   `required_features()` cannot request "the value two positions back".
#   This is a genuine, newly-discovered (beyond breakout/regime)
#   REQUIRED-BUT-UNAVAILABLE dependency, handled the same way: NOT
#   fabricated (e.g. by silently dropping the "rising" half and keeping
#   only "RSI > 50", which would be inventing different semantics), NOT
#   silently omitted without note - simply OMITTED and documented here.
#   Future work: extend `FeatureSeriesComputer`/`Strategy.evaluate()` to
#   expose at least a 1-bar feature lag before this condition can be
#   added.
#
#   BLOCKER C - `regime` labeling (RANGE/BULL_TREND/BEAR_TREND/
#   TRENDING/LOW_TREND, an ADX-threshold-bucketed string). 64.98
#   classified `regime` as REQUIRED BUT UNAVAILABLE. In the reference
#   file `regime` is NOT itself a scoring input to `_score_row()`'s bull/
#   bear totals (it is a separate, informational `_score_row()` return
#   value, attached to the output DataFrame only for display) - so its
#   absence has NO effect on Alpha's actual BUY/SELL/HOLD decision
#   either in the reference or in this adapter. OMITTED (no `regime`
#   field/feature is produced anywhere in this checkpoint).
#
# SCORING (`setup_quality_score`): the reference's numeric weights
# (25/15/12/10/8/7...) are 64.98 UNVERIFIED RESEARCH PARAMETERS, NOT
# verified Gainz mathematics, and are NOT ported here. Where this
# adapter needs a scoring number at all, it uses its OWN, independently
# chosen, equal-weight PROJECT RESEARCH PARAMETER scheme (see
# `_ALPHA_CONDITION_WEIGHT` below) - explicitly documented as adapter-
# owned research scoring, not an official Gainz weight, and NOT
# optimized/tuned in this checkpoint. `setup_quality_score` is carried
# as an extra `FeatureValue` inside `StrategySignal.evidence` (feature
# name `gainz_alpha_setup_quality_score`) - `StrategySignal` itself is a
# FROZEN, shared, multi-strategy contract (Checkpoint 26) that this
# checkpoint does NOT modify; reusing its existing `evidence` tuple
# (already the documented mechanism for "the actual feature conditions
# that contributed to the signal") is the only extension point that
# does not touch that frozen contract. `setup_quality_score` IS NOT A
# PROBABILITY, NOT a probability of profit, NOT a confidence-of-outcome
# estimate - it is a normalized (0-100) count of how many of the
# available shared-base Alpha conditions agreed with the winning
# direction, nothing more.
#
# RISK/POSITION-SIZING BOUNDARY: this adapter NEVER computes final
# position size/quantity/margin/portfolio exposure. The reference's
# `risk_per_trade`/`max_position_value_pct`/`position_size`/`qty`
# fields are NOT read, NOT ported, and have no analog anywhere below.
# Sizing remains the exclusive responsibility of the existing
# RiskDecision stage, downstream of this adapter's `StrategySignal`/
# `TradePlan` output (`StrategySignal -> OrderIntent -> RiskDecision ->
# Existing Execution`).
#
# MIN RR / REQUIRE-CONFIRMED-BAR: the reference's `min_rr` (1.5) was
# previously identified (64.98) as DEAD configuration in the reference
# itself (computed but never gates anything in `generate_gainz_signals`)
# - NOT ported as a live gate here. `require_confirmed_bar` is NOT
# ported as a strategy switch either: closed-candle evaluation is
# already an ARCHITECTURAL execution rule of this platform (every
# `Bar` handed to `evaluate()` is, by the existing backtest/paper
# execution contract, already a CLOSED bar - see
# `coordinator.py`/the canonical backtest engine), not a per-strategy
# toggle to reinvent.
#
# REPEAT-SIGNAL SUPPRESSION: the reference's `disable_repeating_signals`
# / `last_signal` local-state pattern is DELIBERATELY NOT reproduced.
# This class holds NO mutable position/last-signal state between calls
# (every `evaluate()` call is a pure function of its arguments) - if
# duplicate-alert suppression is ever required, it belongs in the
# existing scanner/signal lifecycle (future work), never inside this
# adapter pretending to know the portfolio's current position.
#
# REGISTRATION / LIVE-SCANNER ISOLATION: this class is deliberately NOT
# registered in `registry.build_default_registry()`. That single
# function is the ONE registry construction point shared, verbatim, by
# BOTH the live scanner (`infrastructure/api/scanner_configuration_
# views.py: _registry = build_default_registry()`) AND the backtest API
# (`infrastructure/api/backtesting_views.py: _REGISTRY =
# build_default_registry()`) - this checkpoint independently confirmed
# both call sites construct their registry from that exact same
# function. The existing `StrategyRegistry` architecture has NO
# concept of "research-only" vs "live-scanner-eligible" registration
# (verified: `registry.py` has no such flag/method) - per the directive,
# that gap is NOT patched by weakening the registry; instead, the ONLY
# reachable-from-nowhere-live guarantee available today is to never
# call `.register()` on this class inside `build_default_registry()` at
# all. This exactly mirrors the precedent already established by
# `tests/unit/research/test_checkpoint_64_47_strategy_registry.py`'s own
# `TestStrategy` ("never registered into `build_default_registry()`...
# so this proof-of-concept never pollutes the real strategy suite").
# `test_checkpoint_64_99_gainz_research_adapter.py` proves Strategy-
# protocol/backtest-coordinator compatibility using a LOCAL
# `StrategyRegistry()` instance it constructs itself - never the shared
# one - and separately asserts this class's `strategy_id` is absent
# from `build_default_registry().list()`.
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
from intraday.trading_engine.strategy_execution.errors import InvalidParameterValueError

STRATEGY_ID = "gainz_compatible_research"
DISPLAY_NAME = "Gainz Research Adapter (Gainz-Compatible Research Strategy - profile: alpha)"
SPECIFICATION_VERSION = "v1"
CODE_VERSION = "v1"

# The ONLY implemented profile - see module header. `allowed_values`
# below is deliberately a single-element tuple, so
# `validate_configuration()` (existing, generic - `contracts.py`)
# already rejects any other profile value with `InvalidParameterValueError`
# without this class inventing its own enum-checking code.
PROFILE_ALPHA = "alpha"

# Adapter-owned setup-quality feature name - NOT a canonical field
# registry entry (this is strategy-produced evidence, not a
# `signal_intelligence.feature_engine` feature), carried in
# `StrategySignal.evidence` only. See module header "SCORING".
SETUP_QUALITY_SCORE_FEATURE_NAME = "gainz_alpha_setup_quality_score"
_ADAPTER_EVIDENCE_VERSION = Version(value="v1")

# PROJECT RESEARCH PARAMETER (Checkpoint 64.99) - NOT a Gainz-verified
# weight (see module header "SCORING"). Every one of the 8 implemented
# shared-base conditions counts equally (1 point) toward the winning
# side's setup_quality_score numerator; the denominator is the total
# number of conditions actually evaluated (8, fixed - all 8 are always
# evaluable once required features are present, unlike the reference's
# conditional rel_volume tiers). Deliberately NOT the reference's
# 25/15/12/10/8/7 point scale.
_TOTAL_ALPHA_CONDITIONS = 8


class GainzCompatibleResearchStrategy:
    """Gainz Research Adapter, profile "alpha" - see module header for
    the full condition-by-condition provenance, the two documented
    unavailable-feature blockers (20-bar breakout, RSI momentum), and
    every non-negotiable boundary (risk, sizing, consensus, live-
    scanner isolation) this class respects.

    BULLISH when a majority of the 8 implemented shared-base Alpha
    conditions favor the bullish side over the bearish side; BEARISH
    symmetrically; NEUTRAL (including "no data yet") otherwise. This is
    a RESEARCH RULE SET, NOT verified GainzAlgo V2 signal mathematics.
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
                    parameter_id="profile",
                    label="Gainz Profile",
                    parameter_type=ParameterType.ENUM,
                    required=True,
                    default=PROFILE_ALPHA,
                    allowed_values=(PROFILE_ALPHA,),
                    help_text="The ONLY implemented Gainz research profile in this checkpoint. "
                    "Trend/Breakout/Mean Reversion/Hybrid/Scalp/Consensus are explicitly out "
                    "of scope (Checkpoint 64.99) and are NOT selectable values.",
                ),
                ParameterDefinition(
                    parameter_id="ema_fast_lookback",
                    label="EMA Fast Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=9,
                    minimum=1,
                    maximum=200,
                    help_text="Reference-artifact-default fast EMA period (documentation "
                    "provenance only, NOT a verified Gainz parameter).",
                ),
                ParameterDefinition(
                    parameter_id="ema_slow_lookback",
                    label="EMA Slow Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=21,
                    minimum=2,
                    maximum=400,
                    help_text="Reference-artifact-default slow EMA period.",
                ),
                ParameterDefinition(
                    parameter_id="ema_trend_lookback",
                    label="EMA Trend Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=50,
                    minimum=2,
                    maximum=400,
                    help_text="Reference-artifact-default trend EMA period.",
                ),
                ParameterDefinition(
                    parameter_id="rsi_lookback",
                    label="RSI Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Wilder RSI period (canonical convention - differs numerically "
                    "from the reference's ewm-seeded RSI by design, 64.98).",
                ),
                ParameterDefinition(
                    parameter_id="rsi_alpha_threshold",
                    label="RSI Alpha Threshold",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("80"),
                    minimum=Decimal("50"),
                    maximum=Decimal("100"),
                    help_text="Reference-artifact-default 'not extremely exhausted' gate: "
                    "bull requires RSI < this; bear requires RSI > (100 - this).",
                ),
                ParameterDefinition(
                    parameter_id="price_delta_lookback",
                    label="Price Delta Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=10,
                    minimum=1,
                    maximum=200,
                    help_text="Reference-artifact-default N-bar price-delta reference window.",
                ),
                ParameterDefinition(
                    parameter_id="adx_lookback",
                    label="ADX Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="Wilder ADX/+DI/-DI period.",
                ),
                ParameterDefinition(
                    parameter_id="adx_minimum",
                    label="ADX Minimum (trend-strength gate)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("20"),
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                    help_text="Reference-artifact-default ADX direction-confirmation gate.",
                ),
                ParameterDefinition(
                    parameter_id="relative_volume_lookback",
                    label="Relative Volume Lookback",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=20,
                    minimum=1,
                    maximum=400,
                    help_text="Reference-artifact-default RVOL trailing-average window.",
                ),
                ParameterDefinition(
                    parameter_id="relative_volume_minimum",
                    label="Relative Volume Minimum",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("0.80"),
                    minimum=Decimal("0"),
                    maximum=Decimal("50"),
                    help_text="Reference-artifact-default min_relative_volume gate.",
                ),
                ParameterDefinition(
                    parameter_id="candle_body_ratio_minimum",
                    label="Stable Candle Body Ratio Minimum",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("0.70"),
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                    help_text="Reference-artifact-default candle_stability gate.",
                ),
                ParameterDefinition(
                    parameter_id="macd_fast",
                    label="MACD Fast EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=12,
                    minimum=1,
                    maximum=200,
                    help_text="Standard Appel MACD fast period.",
                ),
                ParameterDefinition(
                    parameter_id="macd_slow",
                    label="MACD Slow EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=26,
                    minimum=2,
                    maximum=400,
                    help_text="Standard Appel MACD slow period.",
                ),
                ParameterDefinition(
                    parameter_id="macd_signal",
                    label="MACD Signal EMA",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=9,
                    minimum=1,
                    maximum=200,
                    help_text="Standard Appel MACD signal period.",
                ),
                # Research-only TradePlan levels - mirrors
                # `atr_volatility_breakout.py`'s existing precedent
                # (ATR-multiplier ladder), NOT the reference's own
                # rr1/rr2/rr3 values ported as verified Gainz math - see
                # `build_trade_plan()` below.
                ParameterDefinition(
                    parameter_id="trade_plan_atr_lookback",
                    label="TradePlan ATR Lookback (research SL/TP only)",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=14,
                    minimum=1,
                    maximum=200,
                    help_text="ATR period used ONLY for research TradePlan SL/TP levels - "
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
                    default=Decimal("1.0"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("20"),
                    help_text="Research-only target-1 distance, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="trade_plan_target_2_atr_multiplier",
                    label="TradePlan Target 2 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("2.0"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("20"),
                    help_text="Research-only target-2 distance, as a multiple of ATR.",
                ),
                ParameterDefinition(
                    parameter_id="trade_plan_target_3_atr_multiplier",
                    label="TradePlan Target 3 (x ATR)",
                    parameter_type=ParameterType.DECIMAL,
                    required=True,
                    default=Decimal("3.0"),
                    minimum=Decimal("0.1"),
                    maximum=Decimal("20"),
                    help_text="Research-only target-3 distance, as a multiple of ATR.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        ema_fast = require_int(config.values, "ema_fast_lookback")
        ema_slow = require_int(config.values, "ema_slow_lookback")
        ema_trend = require_int(config.values, "ema_trend_lookback")
        rsi_lookback = require_int(config.values, "rsi_lookback")
        price_delta_lookback = require_int(config.values, "price_delta_lookback")
        adx_lookback = require_int(config.values, "adx_lookback")
        rvol_lookback = require_int(config.values, "relative_volume_lookback")
        macd_fast = require_int(config.values, "macd_fast")
        macd_slow = require_int(config.values, "macd_slow")
        macd_signal = require_int(config.values, "macd_signal")
        # `atr_{trade_plan_atr_lookback}` is included here (even though
        # it is NOT one of the 8 Alpha bull/bear scoring conditions -
        # `evaluate()` never reads it) purely so `build_trade_plan()`
        # below receives it through the SAME shared-feature-computation
        # path every other strategy in this codebase uses
        # (`StrategyExecutionCoordinator.run()`/`research.backtesting.
        # tradeplan_execution.compute_trade_plans()` both only ever
        # supply a strategy's `required_features()` set to
        # `build_trade_plan()` - there is no second, ATR-only channel).
        # Mirrors `atr_volatility_breakout.py`'s own precedent of
        # declaring the TradePlan-only feature it needs here.
        trade_plan_atr_lookback = require_int(config.values, "trade_plan_atr_lookback")
        return (
            f"ema_{ema_fast}",
            f"ema_{ema_slow}",
            f"ema_{ema_trend}",
            f"rsi_{rsi_lookback}",
            f"price_delta_{price_delta_lookback}",
            f"adx_{adx_lookback}",
            f"plus_di_{adx_lookback}",
            f"minus_di_{adx_lookback}",
            f"relative_volume_{rvol_lookback}",
            f"macd_hist_{macd_fast}_{macd_slow}_{macd_signal}",
            "candle_body_ratio",
            "bullish_engulfing",
            "bearish_engulfing",
            f"atr_{trade_plan_atr_lookback}",
        )

    def _profile(self, config: StrategyConfigurationValues) -> str:
        profile = config.values.get("profile", PROFILE_ALPHA)
        if profile != PROFILE_ALPHA:
            raise InvalidParameterValueError(
                f"strategy {STRATEGY_ID!r}: unsupported profile {profile!r} - "
                f"only {PROFILE_ALPHA!r} is implemented in Checkpoint 64.99"
            )
        return profile

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        # Enforces the single-profile contract even if a caller supplies
        # a config that somehow bypassed `validate_configuration()`.
        self._profile(config)

        (
            ema_fast_name,
            ema_slow_name,
            ema_trend_name,
            rsi_name,
            price_delta_name,
            adx_name,
            plus_di_name,
            minus_di_name,
            rvol_name,
            macd_hist_name,
            body_ratio_name,
            bullish_engulfing_name,
            bearish_engulfing_name,
            _atr_name,  # TradePlan-only - see `required_features()` docstring; not a signal input
        ) = self.required_features(config)

        ema_fast = feature_values.get(ema_fast_name)
        ema_slow = feature_values.get(ema_slow_name)
        ema_trend = feature_values.get(ema_trend_name)
        rsi = feature_values.get(rsi_name)
        price_delta = feature_values.get(price_delta_name)
        adx = feature_values.get(adx_name)
        plus_di = feature_values.get(plus_di_name)
        minus_di = feature_values.get(minus_di_name)
        rvol = feature_values.get(rvol_name)
        macd_hist = feature_values.get(macd_hist_name)
        body_ratio = feature_values.get(body_ratio_name)
        bullish_engulfing = feature_values.get(bullish_engulfing_name)
        bearish_engulfing = feature_values.get(bearish_engulfing_name)

        evidence = (
            ema_fast,
            ema_slow,
            ema_trend,
            rsi,
            price_delta,
            adx,
            plus_di,
            minus_di,
            rvol,
            macd_hist,
            body_ratio,
            bullish_engulfing,
            bearish_engulfing,
        )
        # WARMUP / MISSING-DATA SAFETY: never fabricates a signal when
        # any required canonical feature is unavailable (insufficient
        # warm-up, skipped bar, etc.) - mirrors every existing strategy's
        # documented contract.
        if any(f is None for f in evidence):
            return None
        assert ema_fast is not None
        assert ema_slow is not None
        assert ema_trend is not None
        assert rsi is not None
        assert price_delta is not None
        assert adx is not None
        assert plus_di is not None
        assert minus_di is not None
        assert rvol is not None
        assert macd_hist is not None
        assert body_ratio is not None
        assert bullish_engulfing is not None
        assert bearish_engulfing is not None

        rsi_alpha_threshold = require_decimal(config.values, "rsi_alpha_threshold")
        adx_minimum = require_decimal(config.values, "adx_minimum")
        rvol_minimum = require_decimal(config.values, "relative_volume_minimum")
        body_ratio_minimum = require_decimal(config.values, "candle_body_ratio_minimum")

        price = bar.close
        stable_candle = body_ratio.value >= body_ratio_minimum
        trend_bull = (
            price > ema_trend.value
            and ema_fast.value > ema_slow.value
            and ema_slow.value > ema_trend.value
        )
        trend_bear = (
            price < ema_trend.value
            and ema_fast.value < ema_slow.value
            and ema_slow.value < ema_trend.value
        )
        adx_trend_strong = adx.value >= adx_minimum
        volume_confirmed = rvol.value >= rvol_minimum
        candle_bullish = bar.close > bar.open
        candle_bearish = bar.close < bar.open

        # Each of the 8 implemented shared-base Alpha conditions below is
        # an independent True/False - equal-weight PROJECT RESEARCH
        # PARAMETER scoring (see module header "SCORING"), NOT the
        # reference's 25/15/12/10/8/7 point scale.
        bull_conditions = (
            bullish_engulfing.value == 1,
            stable_candle,
            rsi.value < rsi_alpha_threshold,
            price_delta.value < 0,
            trend_bull,
            macd_hist.value > 0,
            volume_confirmed and candle_bullish,
            adx_trend_strong and plus_di.value > minus_di.value,
        )
        bear_conditions = (
            bearish_engulfing.value == 1,
            stable_candle,
            rsi.value > (Decimal("100") - rsi_alpha_threshold),
            price_delta.value > 0,
            trend_bear,
            macd_hist.value < 0,
            volume_confirmed and candle_bearish,
            adx_trend_strong and minus_di.value > plus_di.value,
        )
        bull_score = sum(1 for c in bull_conditions if c)
        bear_score = sum(1 for c in bear_conditions if c)

        if bull_score > bear_score and bull_score > 0:
            direction = StrategyDirection.BULLISH
            winning_score = bull_score
        elif bear_score > bull_score and bear_score > 0:
            direction = StrategyDirection.BEARISH
            winning_score = bear_score
        else:
            direction = StrategyDirection.NEUTRAL
            winning_score = 0

        setup_quality_score = FeatureValue(
            feature_name=SETUP_QUALITY_SCORE_FEATURE_NAME,
            feature_version=_ADAPTER_EVIDENCE_VERSION,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            # 0..100, NOT a probability - see module header "SCORING".
            value=(Decimal(winning_score) / Decimal(_TOTAL_ALPHA_CONDITIONS)) * Decimal(100),
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
            evidence=evidence + (setup_quality_score,),  # type: ignore[arg-type]
        )

    def build_trade_plan(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
        signal: StrategySignal,
    ) -> TradePlan | None:
        """Research-only TradePlan, reusing the EXISTING `TradePlan`
        contract unchanged (`target_1`/`target_2`/`target_3` - no schema
        change). `entry_price` here is signal-time close: an ENTRY
        CANDIDATE/REFERENCE PRICE ONLY, never a same-candle-close fill -
        actual historical fills remain NEXT-BAR-OPEN via the existing,
        unchanged backtest engine. ATR-multiplier ladder mirrors
        `atr_volatility_breakout.py`'s existing precedent - NOT the
        reference's rr1/rr2/rr3 ported as verified Gainz risk:reward
        math (its own `min_rr` was independently found dead - see module
        header). Returns `None` for NEUTRAL or missing ATR (never
        fabricates a plan from missing data)."""
        if signal.direction is StrategyDirection.NEUTRAL:
            return None

        try:
            atr_lookback = require_int(config.values, "trade_plan_atr_lookback")
            stop_multiplier = require_decimal(config.values, "trade_plan_stop_loss_atr_multiplier")
            target_1_multiplier = require_decimal(
                config.values, "trade_plan_target_1_atr_multiplier"
            )
            target_2_multiplier = require_decimal(
                config.values, "trade_plan_target_2_atr_multiplier"
            )
            target_3_multiplier = require_decimal(
                config.values, "trade_plan_target_3_atr_multiplier"
            )
        except (KeyError, InvalidParameterValueError):
            return None

        atr = feature_values.get(f"atr_{atr_lookback}")
        if atr is None:
            # Advisory-only: `atr_{lookback}` is not part of
            # `required_features()` above (not an Alpha signal
            # condition) - a caller must separately supply it for a
            # research TradePlan to be produced. Never fabricated.
            return None

        entry = signal.price
        atr_value = atr.value
        sign = 1 if signal.direction is StrategyDirection.BULLISH else -1

        return TradePlan(
            strategy_id=self.strategy_id,
            code_version=self.code_version,
            generated_at=datetime.now(UTC),
            calculation_method=(
                "RESEARCH-ONLY (NOT verified GainzAlgo V2 TP/SL math), profile=alpha: "
                f"entry=signal-time close ({entry}), an ENTRY CANDIDATE/REFERENCE PRICE ONLY "
                "(actual backtest fill remains next-bar-open, unchanged); "
                f"stop_loss=entry-{sign}*{stop_multiplier}xATR({atr_lookback}); "
                f"target_1..3=entry+{sign}*[{target_1_multiplier},{target_2_multiplier},"
                f"{target_3_multiplier}]xATR({atr_lookback}). ATR={atr_value} at signal time."
            ),
            entry_price=entry,
            stop_loss=entry - sign * stop_multiplier * atr_value,
            target_1=entry + sign * target_1_multiplier * atr_value,
            target_2=entry + sign * target_2_multiplier * atr_value,
            target_3=entry + sign * target_3_multiplier * atr_value,
        )
