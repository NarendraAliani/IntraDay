# File: tests/unit/research/test_checkpoint_gainz_c_presets.py
#
# CHECKPOINT-GAINZ-C: three `StrategyConfigurationRecord` presets
# (`gainz_conservative`/`gainz_balanced`/`gainz_aggressive`) for
# `gainz_compatible_research` (`code_version="v3"`, the
# CHECKPOINT-GAINZ-C `minimum_setup_quality_score` gate - see that
# strategy module's header). This checkpoint does NOT touch
# `registry.py` (the strategy remains unregistered/unreachable from the
# live scanner or backtest API) - a LOCAL `StrategyRegistry()` instance
# is constructed here, exactly mirroring
# `test_checkpoint_64_99_gainz_research_adapter.py`'s own precedent,
# never the shared `build_default_registry()`.
#
# Uses the REAL `DjangoStrategyConfigurationRepository` against the test
# database (Postgres, `@requires_postgres`/`@pytest.mark.django_db`,
# same convention as `test_strategy_configuration_repository.py`) - this
# checkpoint's whole point is proving 3 REAL, PERSISTED, DISTINCT rows
# exist and are individually retrievable, not merely that an in-memory
# fake accepts them.
from __future__ import annotations

import datetime as _dt
from decimal import Decimal, getcontext

import pytest

from intraday.application.services.strategy_configuration import StrategyConfigurationService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version
from intraday.infrastructure.persistence.models import StrategyConfigurationRecord
from intraday.infrastructure.persistence.repositories import DjangoStrategyConfigurationRepository
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    coerce_configuration_values,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    CODE_VERSION,
    REJECTION_REASON_BELOW_QUALITY_THRESHOLD,
    REJECTION_REASON_NOT_REJECTED,
    SETUP_QUALITY_SCORE_FEATURE_NAME,
    SPECIFICATION_VERSION,
    STRATEGY_ID,
    GainzCompatibleResearchStrategy,
)
from tests.postgres_utils import requires_postgres

# ---------------------------------------------------------------------------
# The 3 presets - identical structure to the module-level docstring math
# reported to the orchestrating session. `minimum_setup_quality_score`
# is the only gating-relevant number that differs by threshold tier;
# `adx_minimum`/`relative_volume_minimum`/`candle_body_ratio_minimum`/
# `rsi_alpha_threshold` vary risk-strictness; `rolling_breakout_lookback`
# and every indicator-lookback-window parameter are IDENTICAL across all
# 3 (feature parameters, not risk parameters - per the directive).
# ---------------------------------------------------------------------------

CONSERVATIVE_VERSION = "gainz_conservative"
BALANCED_VERSION = "gainz_balanced"  # default research profile, per GAINZ_ROADMAP.md
AGGRESSIVE_VERSION = "gainz_aggressive"  # correct spelling - deliberate, see summary


def _shared_values() -> dict[str, object]:
    """Parameters identical across all 3 presets - schema defaults for
    every indicator lookback window and every TradePlan-only field."""
    return {
        "profile": "alpha",
        "ema_fast_lookback": 9,
        "ema_slow_lookback": 21,
        "ema_trend_lookback": 50,
        "rsi_lookback": 14,
        "price_delta_lookback": 10,
        "adx_lookback": 14,
        "relative_volume_lookback": 20,
        "rolling_breakout_lookback": 20,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "trade_plan_atr_lookback": 14,
        "trade_plan_stop_loss_atr_multiplier": "1.0",
        "trade_plan_target_1_atr_multiplier": "1.0",
        "trade_plan_target_2_atr_multiplier": "2.0",
        "trade_plan_target_3_atr_multiplier": "3.0",
    }


def conservative_values() -> dict[str, object]:
    values = _shared_values()
    values.update(
        {
            "minimum_setup_quality_score": "70",
            "adx_minimum": "25",
            "relative_volume_minimum": "1.00",
            "candle_body_ratio_minimum": "0.80",
            "rsi_alpha_threshold": "70",
        }
    )
    return values


def balanced_values() -> dict[str, object]:
    values = _shared_values()
    values.update(
        {
            "minimum_setup_quality_score": "55",
            "adx_minimum": "20",
            "relative_volume_minimum": "0.80",
            "candle_body_ratio_minimum": "0.70",
            "rsi_alpha_threshold": "80",
        }
    )
    return values


def aggressive_values() -> dict[str, object]:
    values = _shared_values()
    values.update(
        {
            "minimum_setup_quality_score": "40",
            "adx_minimum": "15",
            "relative_volume_minimum": "0.60",
            "candle_body_ratio_minimum": "0.60",
            "rsi_alpha_threshold": "85",
        }
    )
    return values


def _local_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    return registry


def _service() -> StrategyConfigurationService:
    return StrategyConfigurationService(
        repository=DjangoStrategyConfigurationRepository(), registry=_local_registry()
    )


# ---------------------------------------------------------------------------
# 1. Creation, count, retrievability, distinctness.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_1_three_presets_created_retrievable_and_distinct() -> None:
    before = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert before == 0

    service = _service()
    for configuration_version, values in (
        (CONSERVATIVE_VERSION, conservative_values()),
        (BALANCED_VERSION, balanced_values()),
        (AGGRESSIVE_VERSION, aggressive_values()),
    ):
        snapshot = service.save_configuration(
            STRATEGY_ID,
            SPECIFICATION_VERSION,
            CODE_VERSION,
            configuration_version,
            values,
            created_by="checkpoint-gainz-c",
        )
        assert snapshot.configuration_version == configuration_version

    after = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert after == 3

    repo = DjangoStrategyConfigurationRepository()
    conservative = repo.get(STRATEGY_ID, SPECIFICATION_VERSION, CODE_VERSION, CONSERVATIVE_VERSION)
    balanced = repo.get(STRATEGY_ID, SPECIFICATION_VERSION, CODE_VERSION, BALANCED_VERSION)
    aggressive = repo.get(STRATEGY_ID, SPECIFICATION_VERSION, CODE_VERSION, AGGRESSIVE_VERSION)
    assert conservative is not None and balanced is not None and aggressive is not None

    # Distinct: differ on every risk/strictness parameter varied.
    assert conservative.parameter_values["minimum_setup_quality_score"] == "70"
    assert balanced.parameter_values["minimum_setup_quality_score"] == "55"
    assert aggressive.parameter_values["minimum_setup_quality_score"] == "40"
    assert (
        conservative.parameter_values
        != balanced.parameter_values
        != aggressive.parameter_values
    )
    # `rolling_breakout_lookback` deliberately identical (feature
    # parameter, not risk parameter - per the directive).
    assert (
        conservative.parameter_values["rolling_breakout_lookback"]
        == balanced.parameter_values["rolling_breakout_lookback"]
        == aggressive.parameter_values["rolling_breakout_lookback"]
        == 20
    )


@requires_postgres
@pytest.mark.django_db
def test_2_each_preset_parses_through_coerce_and_validate_into_valid_values() -> None:
    """Confirms each preset's `parameter_values` (as persisted - JSON-safe
    strings for DECIMAL parameters) parses correctly through
    `coerce_configuration_values()` into a valid `StrategyConfigurationValues`,
    same validation path `StrategyConfigurationService.save_configuration()`
    already exercised at write time - re-derived independently here."""
    schema = GainzCompatibleResearchStrategy().parameter_schema()
    known_field_ids = frozenset(
        {
            "ema_9",
            "ema_21",
            "ema_50",
            "rsi_14",
            "price_delta_10",
            "adx_14",
            "plus_di_14",
            "minus_di_14",
            "relative_volume_20",
            "macd_hist_12_26_9",
            "candle_body_ratio",
            "bullish_engulfing",
            "bearish_engulfing",
            "rolling_breakout_20",
            "atr_14",
        }
    )
    for values in (conservative_values(), balanced_values(), aggressive_values()):
        coerced = coerce_configuration_values(schema, values)
        assert isinstance(coerced["minimum_setup_quality_score"], Decimal)
        assert isinstance(coerced["adx_minimum"], Decimal)
        validate_configuration(schema, coerced, known_field_ids=known_field_ids)
        config = StrategyConfigurationValues(
            STRATEGY_ID, SPECIFICATION_VERSION, CODE_VERSION, "cfg-test", coerced
        )
        assert config.values["minimum_setup_quality_score"] == Decimal(
            values["minimum_setup_quality_score"]
        )


# ---------------------------------------------------------------------------
# Shared `evaluate()` feature-set helpers - same style as
# test_checkpoint_gainz_b1_scoring_and_breakout.py's `_base_feature_values`.
# ---------------------------------------------------------------------------

IID = InstrumentId("NSE:GAINZCTEST")
TF = Timeframe.ONE_MINUTE
TS = _dt.datetime(2026, 1, 5, 4, 0, tzinfo=_dt.UTC)
FV_VERSION = Version(value="v1")

EMA_FAST, EMA_SLOW, EMA_TREND = "ema_9", "ema_21", "ema_50"
RSI, PRICE_DELTA, ADX = "rsi_14", "price_delta_10", "adx_14"
PLUS_DI, MINUS_DI, RVOL = "plus_di_14", "minus_di_14", "relative_volume_20"
MACD_HIST = "macd_hist_12_26_9"
BODY_RATIO, BULL_ENGULF, BEAR_ENGULF = "candle_body_ratio", "bullish_engulfing", "bearish_engulfing"
ROLLING_BREAKOUT = "rolling_breakout_20"


def _fv(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FV_VERSION,
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        value=Decimal(value),
    )


def _bar(close: str, *, open_: str) -> Bar:
    o = Decimal(open_)
    c = Decimal(close)
    hi = max(o, c) + Decimal("1")
    lo = min(o, c) - Decimal("1")
    return Bar(
        instrument_id=IID, timeframe=TF, timestamp=TS, open=o, high=hi, low=lo, close=c,
        volume=Decimal("1000"),
    )


def _score(signal) -> Decimal:
    return next(
        fv.value for fv in signal.evidence if fv.feature_name == SETUP_QUALITY_SCORE_FEATURE_NAME
    )


def _config_from(values: dict[str, object], configuration_version: str) -> StrategyConfigurationValues:
    schema = GainzCompatibleResearchStrategy().parameter_schema()
    coerced = coerce_configuration_values(schema, values)
    return StrategyConfigurationValues(
        STRATEGY_ID, SPECIFICATION_VERSION, CODE_VERSION, configuration_version, coerced
    )


def _score_68_bull_feature_values() -> dict[str, FeatureValue]:
    """bull_true=6, bear_true=1 -> bull_score=66.667, bear_score=11.111
    -> setup_quality_score = 0.72*66.667 + 0.28*(55.556/77.778*100)
                            = 0.72*(200/3) + 0.28*(500/7) = 48 + 20 = 68
    exactly (identical hand arithmetic to
    test_checkpoint_gainz_b1_scoring_and_breakout.py's test_1).
    Bull-true conditions: bullish_engulfing==1, stable_candle
    (body_ratio 0.90 >= even the conservative preset's 0.80 minimum),
    rsi<80 (rsi=15), trend_bull, macd_hist>0, volume+bullish-candle
    (rvol=1.20 >= even the conservative preset's 1.00 minimum).
    Bull-false: price_delta (0, neither), adx (10 < even the aggressive
    preset's 15 minimum -> both bull8/bear8 False), rolling_breakout (0,
    neither). Bear-true: only the shared stable_candle -> bear_true=1.
    """
    return {
        EMA_FAST: _fv(EMA_FAST, "110"),
        EMA_SLOW: _fv(EMA_SLOW, "105"),
        EMA_TREND: _fv(EMA_TREND, "100"),
        RSI: _fv(RSI, "15"),
        PRICE_DELTA: _fv(PRICE_DELTA, "0"),
        ADX: _fv(ADX, "10"),
        PLUS_DI: _fv(PLUS_DI, "10"),
        MINUS_DI: _fv(MINUS_DI, "10"),
        RVOL: _fv(RVOL, "1.20"),
        MACD_HIST: _fv(MACD_HIST, "5"),
        BODY_RATIO: _fv(BODY_RATIO, "0.90"),
        BULL_ENGULF: _fv(BULL_ENGULF, "1"),
        BEAR_ENGULF: _fv(BEAR_ENGULF, "0"),
        ROLLING_BREAKOUT: _fv(ROLLING_BREAKOUT, "0"),
    }


def _score_52_bull_feature_values() -> dict[str, FeatureValue]:
    """bull_true=5, bear_true=2 -> bull_score=55.556, bear_score=22.222
    -> setup_quality_score = 0.72*55.556 + 0.28*(33.333/77.778*100)
                            = 0.72*(500/9) + 0.28*(300/7) = 40 + 12 = 52
    exactly. Bull-true: bullish_engulfing==1, stable_candle, rsi<80
    (rsi=50, ALSO satisfies bear's rsi>20 -> shared with bear), trend_bull,
    macd_hist>0. Bull-false: price_delta (0), volume+candle (rvol=0.50,
    below every preset's minimum), adx (10, below every preset's
    minimum), rolling_breakout (0). Bear-true: stable_candle + rsi>20
    (both shared with bull via rsi=50) -> bear_true=2.
    """
    return {
        EMA_FAST: _fv(EMA_FAST, "110"),
        EMA_SLOW: _fv(EMA_SLOW, "105"),
        EMA_TREND: _fv(EMA_TREND, "100"),
        RSI: _fv(RSI, "50"),
        PRICE_DELTA: _fv(PRICE_DELTA, "0"),
        ADX: _fv(ADX, "10"),
        PLUS_DI: _fv(PLUS_DI, "10"),
        MINUS_DI: _fv(MINUS_DI, "10"),
        RVOL: _fv(RVOL, "0.50"),
        MACD_HIST: _fv(MACD_HIST, "5"),
        BODY_RATIO: _fv(BODY_RATIO, "0.90"),
        BULL_ENGULF: _fv(BULL_ENGULF, "1"),
        BEAR_ENGULF: _fv(BEAR_ENGULF, "0"),
        ROLLING_BREAKOUT: _fv(ROLLING_BREAKOUT, "0"),
    }


def _score_25_bull_feature_values() -> dict[str, FeatureValue]:
    """bull_true=2, bear_true=1 -> bull_score=22.222, bear_score=11.111
    -> setup_quality_score = 0.72*(200/9) + 0.28*(100/3)
                            = 16 + 9.33333... = 25.33333...
    (a non-terminating repeating decimal at 28-digit Decimal precision -
    compared with a tolerance below, same convention
    test_checkpoint_gainz_b1_scoring_and_breakout.py's
    test_3_balanced_tie_case_is_neutral_with_zero_separation already
    established for a non-exact result).

    Bull-true: bullish_engulfing==1 (condition 1), plus the SHARED rsi
    gate (condition 3: rsi=50 satisfies bull's `rsi<rsi_alpha_threshold`
    for EVERY preset's threshold - 70/80/85 - AND ALSO bear's
    `rsi>100-rsi_alpha_threshold` for every preset - complements
    30/20/15 - so this condition is DELIBERATELY chosen to land True on
    BOTH sides identically regardless of which preset is in effect;
    unlike adx_minimum/relative_volume_minimum/candle_body_ratio_minimum
    below, rsi_alpha_threshold cannot be neutralized to False-for-both
    by any single rsi value across all 3 presets at once - see the
    checkpoint summary for the derivation of why). Bear-true: only that
    same shared rsi condition -> bear_true=1 (bearish_engulfing left
    0/False). Everything else False on both sides via values BELOW
    every preset's own minimum (body_ratio 0.50 < even balanced's 0.70,
    rvol 0.50 < even aggressive's 0.60, adx 10 < even aggressive's 15),
    plus flat EMAs/zero price_delta/zero macd_hist/zero rolling_breakout
    satisfying neither direction."""
    return {
        EMA_FAST: _fv(EMA_FAST, "100"),
        EMA_SLOW: _fv(EMA_SLOW, "100"),
        EMA_TREND: _fv(EMA_TREND, "100"),
        RSI: _fv(RSI, "50"),
        PRICE_DELTA: _fv(PRICE_DELTA, "0"),
        ADX: _fv(ADX, "10"),
        PLUS_DI: _fv(PLUS_DI, "10"),
        MINUS_DI: _fv(MINUS_DI, "10"),
        RVOL: _fv(RVOL, "0.50"),
        MACD_HIST: _fv(MACD_HIST, "0"),
        BODY_RATIO: _fv(BODY_RATIO, "0.50"),
        BULL_ENGULF: _fv(BULL_ENGULF, "1"),
        BEAR_ENGULF: _fv(BEAR_ENGULF, "0"),
        ROLLING_BREAKOUT: _fv(ROLLING_BREAKOUT, "0"),
    }


# ---------------------------------------------------------------------------
# 3/4/5. Per-preset gating proof - one test PER preset, using the SAME
# feature set across all 3 presets to show the gate genuinely
# differentiates BULLISH/BEARISH vs NEUTRAL(BELOW_QUALITY_THRESHOLD).
# ---------------------------------------------------------------------------


def test_3_conservative_preset_rejects_a_score_that_balanced_and_aggressive_accept() -> None:
    """score=68 (exact, see docstring above): 68 >= aggressive's 40 and
    >= balanced's 55 (both BULLISH) but 68 < conservative's 70
    (NEUTRAL, REJECTED_BELOW_QUALITY_THRESHOLD) - proves the
    conservative preset's own threshold, specifically, is what changes
    the outcome versus the other two."""
    getcontext().prec = 28
    feature_values = _score_68_bull_feature_values()
    bar = _bar("110", open_="100")

    aggressive_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(aggressive_values(), AGGRESSIVE_VERSION)
    )
    balanced_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(balanced_values(), BALANCED_VERSION)
    )
    conservative_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(conservative_values(), CONSERVATIVE_VERSION)
    )

    assert aggressive_signal is not None and balanced_signal is not None and conservative_signal is not None
    assert _score(aggressive_signal) == Decimal(68)
    assert _score(balanced_signal) == Decimal(68)
    assert _score(conservative_signal) == Decimal(68)

    assert aggressive_signal.direction is StrategyDirection.BULLISH
    assert balanced_signal.direction is StrategyDirection.BULLISH
    assert conservative_signal.direction is StrategyDirection.NEUTRAL

    rejection = next(
        fv.value
        for fv in conservative_signal.evidence
        if fv.feature_name == "gainz_alpha_rejection_reason_code"
    )
    assert rejection == REJECTION_REASON_BELOW_QUALITY_THRESHOLD


def test_4_balanced_preset_rejects_a_score_that_only_aggressive_accepts() -> None:
    """score=52 (exact, see docstring above): 52 >= aggressive's 40
    (BULLISH) but 52 < balanced's 55 and < conservative's 70 (both
    NEUTRAL) - proves the balanced preset's own threshold is the one
    differentiating it from aggressive here."""
    feature_values = _score_52_bull_feature_values()
    bar = _bar("110", open_="100")

    aggressive_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(aggressive_values(), AGGRESSIVE_VERSION)
    )
    balanced_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(balanced_values(), BALANCED_VERSION)
    )
    conservative_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(conservative_values(), CONSERVATIVE_VERSION)
    )

    assert aggressive_signal is not None and balanced_signal is not None and conservative_signal is not None
    assert _score(aggressive_signal) == Decimal(52)
    assert _score(balanced_signal) == Decimal(52)
    assert _score(conservative_signal) == Decimal(52)

    assert aggressive_signal.direction is StrategyDirection.BULLISH
    assert balanced_signal.direction is StrategyDirection.NEUTRAL
    assert conservative_signal.direction is StrategyDirection.NEUTRAL

    for signal in (balanced_signal, conservative_signal):
        rejection = next(
            fv.value
            for fv in signal.evidence
            if fv.feature_name == "gainz_alpha_rejection_reason_code"
        )
        assert rejection == REJECTION_REASON_BELOW_QUALITY_THRESHOLD


def test_5_aggressive_preset_still_rejects_a_very_weak_score() -> None:
    """score=25.333... (see docstring above), below ALL 3 presets'
    thresholds (40/55/70) - proves the aggressive preset (the loosest
    of the 3) is NOT a no-op/inert config: it still genuinely gates a
    sufficiently weak signal, exactly as the default (`minimum_setup_
    quality_score=0`, a deliberate no-op per the strategy module's own
    docstring) would NOT have."""
    feature_values = _score_25_bull_feature_values()
    bar = _bar("100", open_="100")

    aggressive_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(aggressive_values(), AGGRESSIVE_VERSION)
    )
    balanced_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(balanced_values(), BALANCED_VERSION)
    )
    conservative_signal = GainzCompatibleResearchStrategy().evaluate(
        bar, feature_values, _config_from(conservative_values(), CONSERVATIVE_VERSION)
    )

    assert aggressive_signal is not None and balanced_signal is not None and conservative_signal is not None
    assert abs(_score(aggressive_signal) - Decimal("25.33333333333333333333333333")) < Decimal("1e-20")

    assert aggressive_signal.direction is StrategyDirection.NEUTRAL
    assert balanced_signal.direction is StrategyDirection.NEUTRAL
    assert conservative_signal.direction is StrategyDirection.NEUTRAL

    for signal in (aggressive_signal, balanced_signal, conservative_signal):
        rejection = next(
            fv.value
            for fv in signal.evidence
            if fv.feature_name == "gainz_alpha_rejection_reason_code"
        )
        assert rejection == REJECTION_REASON_BELOW_QUALITY_THRESHOLD

    # Sanity: with the NO-OP default (0), this exact weak signal would
    # have been emitted directional (BULLISH), not NEUTRAL - confirms
    # the gate, not some other unrelated condition, causes the rejection.
    default_config = StrategyConfigurationValues(
        STRATEGY_ID,
        SPECIFICATION_VERSION,
        CODE_VERSION,
        "cfg-default-no-op",
        {**_config_from(aggressive_values(), AGGRESSIVE_VERSION).values, "minimum_setup_quality_score": Decimal("0")},
    )
    default_signal = GainzCompatibleResearchStrategy().evaluate(bar, feature_values, default_config)
    assert default_signal is not None
    assert default_signal.direction is StrategyDirection.BULLISH
    default_rejection = next(
        fv.value
        for fv in default_signal.evidence
        if fv.feature_name == "gainz_alpha_rejection_reason_code"
    )
    assert default_rejection == REJECTION_REASON_NOT_REJECTED
