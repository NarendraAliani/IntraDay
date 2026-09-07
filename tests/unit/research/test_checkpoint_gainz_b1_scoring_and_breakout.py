# File: tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py
#
# CHECKPOINT-GAINZ-B1: extends `gainz_compatible_research.py` in place
# (`code_version` "v1" -> "v2"). Two behavior changes under direct test
# here:
#
#   (1) The new 0.72*dominant_score + 0.28*separation scoring formula
#       (bull_score/bear_score = proportion, 0..100, of the 9
#       directional conditions satisfied) - REPLACING 64.99's
#       equal-weight winning-count/8 scheme.
#   (2) `rolling_breakout` wired in as a genuine 9th condition (BLOCKER
#       A, closed) - proven to actually change the emitted direction,
#       not merely "present but inert".
#
# Style: constructs `feature_values` dicts DIRECTLY (bypassing bar-series
# feature computation) so every one of the 9 bull/9 bear conditions can
# be independently pinned to an exact True/False, making the hand
# arithmetic in each test's docstring exactly reproducible - the same
# level of control `test_checkpoint_64_99_gainz_research_adapter.py`
# achieves indirectly via engineered bar sequences, but exact rather
# than "engineered to probably work out".
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, getcontext

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
)
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    CODE_VERSION,
    REJECTION_REASON_CODE_FEATURE_NAME,
    REJECTION_REASON_NOT_REJECTED,
    REJECTION_REASON_TIE,
    SETUP_QUALITY_SCORE_FEATURE_NAME,
    STRATEGY_ID,
    GainzCompatibleResearchStrategy,
)

IID = InstrumentId("NSE:GAINZB1TEST")
TF = Timeframe.ONE_MINUTE
TS = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
FV_VERSION = Version(value="v1")


def _bar(close: str, *, open_: str | None = None) -> Bar:
    o = Decimal(open_ if open_ is not None else close)
    c = Decimal(close)
    hi = max(o, c) + Decimal("1")
    lo = min(o, c) - Decimal("1")
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        open=o,
        high=hi,
        low=lo,
        close=c,
        volume=Decimal("1000"),
    )


def _fv(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FV_VERSION,
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        value=Decimal(value),
    )


def _config(**overrides: object) -> StrategyConfigurationValues:
    strategy = GainzCompatibleResearchStrategy()
    values: dict[str, object] = {}
    for p in strategy.parameter_schema().parameters:
        if p.default is not None:
            values[p.parameter_id] = p.default
    values.update(overrides)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", CODE_VERSION, "v1", values)


def _strategy() -> GainzCompatibleResearchStrategy:
    return GainzCompatibleResearchStrategy()


# Canonical field names produced by the DEFAULT configuration (matches
# `GainzCompatibleResearchStrategy.required_features()` with all
# defaults - `ema_fast_lookback=9`, `ema_slow_lookback=21`,
# `ema_trend_lookback=50`, `rsi_lookback=14`, `price_delta_lookback=10`,
# `adx_lookback=14`, `relative_volume_lookback=20`,
# `macd_fast/slow/signal=12/26/9`, `rolling_breakout_lookback=20`).
EMA_FAST, EMA_SLOW, EMA_TREND = "ema_9", "ema_21", "ema_50"
RSI, PRICE_DELTA, ADX = "rsi_14", "price_delta_10", "adx_14"
PLUS_DI, MINUS_DI, RVOL = "plus_di_14", "minus_di_14", "relative_volume_20"
MACD_HIST = "macd_hist_12_26_9"
BODY_RATIO, BULL_ENGULF, BEAR_ENGULF = "candle_body_ratio", "bullish_engulfing", "bearish_engulfing"
ROLLING_BREAKOUT = "rolling_breakout_20"


def _base_feature_values(
    *,
    bullish_engulfing: str = "0",
    bearish_engulfing: str = "0",
    body_ratio: str = "0.50",  # below default 0.70 minimum -> stable_candle False
    rsi: str = "50",  # neither exhausted-bull (< 80) nor exhausted-bear (> 20) trap avoided per-case
    price_delta: str = "0",  # neither < 0 nor > 0
    ema_fast: str = "100",
    ema_slow: str = "100",
    ema_trend: str = "100",
    price: str = "100",  # bar.close - must match _bar() argument in each test
    macd_hist: str = "0",
    rvol: str = "0.50",  # below default 0.80 minimum -> volume_confirmed False
    adx: str = "10",  # below default 20 minimum -> adx_trend_strong False
    plus_di: str = "10",
    minus_di: str = "10",
    rolling_breakout: str = "0",
) -> dict[str, FeatureValue]:
    return {
        EMA_FAST: _fv(EMA_FAST, ema_fast),
        EMA_SLOW: _fv(EMA_SLOW, ema_slow),
        EMA_TREND: _fv(EMA_TREND, ema_trend),
        RSI: _fv(RSI, rsi),
        PRICE_DELTA: _fv(PRICE_DELTA, price_delta),
        ADX: _fv(ADX, adx),
        PLUS_DI: _fv(PLUS_DI, plus_di),
        MINUS_DI: _fv(MINUS_DI, minus_di),
        RVOL: _fv(RVOL, rvol),
        MACD_HIST: _fv(MACD_HIST, macd_hist),
        BODY_RATIO: _fv(BODY_RATIO, body_ratio),
        BULL_ENGULF: _fv(BULL_ENGULF, bullish_engulfing),
        BEAR_ENGULF: _fv(BEAR_ENGULF, bearish_engulfing),
        ROLLING_BREAKOUT: _fv(ROLLING_BREAKOUT, rolling_breakout),
    }


def _score(signal) -> Decimal:
    return next(
        fv.value for fv in signal.evidence if fv.feature_name == SETUP_QUALITY_SCORE_FEATURE_NAME
    )


def _rejection_code(signal) -> Decimal:
    return next(
        fv.value for fv in signal.evidence if fv.feature_name == REJECTION_REASON_CODE_FEATURE_NAME
    )


# ---------------------------------------------------------------------------
# 1. Scoring formula - bull-heavy case, full hand arithmetic.
# ---------------------------------------------------------------------------


def test_1_bull_heavy_case_hand_computed_score() -> None:
    """6 of 9 bullish conditions true, 1 of 9 bearish conditions true.

    Bull conditions made True: (1) bullish_engulfing==1, (3) rsi<80,
    (4) price_delta<0, (5) trend_bull (price>ema_trend, ema_fast>
    ema_slow>ema_trend), (6) macd_hist>0, (9) rolling_breakout==1.
    Bull conditions False: (2) stable_candle (body_ratio 0.50 < 0.70),
    (7) volume+candle (rvol 0.50 < 0.80), (8) adx (adx 10 < 20).
    -> bull_true_count = 6.

    Bear conditions: only (2) stable_candle is shared with bull and is
    False here too, so ALL 9 bear conditions are False EXCEPT we pin
    exactly one True by construction below to get bear_true_count = 1:
    bearish_engulfing is left 0 (False) but rsi's bear gate
    (rsi > 100-80=20) is ALSO False since rsi=10 here (< 20) - so
    instead we deliberately flip `bearish_engulfing` to 1 to produce
    the 1 true bear condition cleanly (all others structurally False
    given the same feature values that make bull true: price_delta<0
    means bear's price_delta>0 is False; trend_bull true means
    trend_bear is False by construction; macd_hist>0 means bear's <0 is
    False; rolling_breakout==1 means bear's ==-1 is False).

    Hand arithmetic (exact fractions, matching the implementation's
    Decimal arithmetic order):
        bull_score = 6/9 * 100 = 66.66666...
        bear_score = 1/9 * 100 = 11.11111...
        dominant_score = max(66.667, 11.111) = 66.66666...
        separation = |66.667 - 11.111| / max(66.667+11.111, 1) * 100
                   = 55.55556 / 77.77778 * 100
                   = 71.42857...  (= 500/7 exactly, since
                     55.55556/77.77778 = (500/9)/(700/9) = 500/700 = 5/7)
        setup_quality_score = 0.72 * 66.66667 + 0.28 * 71.42857
                            = 48.00000 + 20.00000
                            = 68.00000
    (0.72 * 200/3 = 144/3 = 48 exactly; 0.28 * 500/7 = 140/7 = 20
    exactly - both terms are exact despite the intermediate
    bull_score/separation being repeating decimals, so the final total
    is exactly 68, asserted with an exact equality below using the
    project's own Decimal precision, not a magic number.)
    """
    getcontext().prec = 28  # project-default Decimal context, explicit for reproducibility
    feature_values = _base_feature_values(
        bullish_engulfing="1",
        bearish_engulfing="1",  # the ONE true bear condition (bear cond 1)
        body_ratio="0.50",  # stable_candle False for both
        rsi="10",  # bull: 10 < 80 True; bear: 10 > 20 False
        price_delta="-5",  # bull: <0 True; bear: >0 False
        ema_fast="120",
        ema_slow="110",
        ema_trend="100",
        price="130",  # trend_bull: 130>100 and 120>110>100 -> True; trend_bear False
        macd_hist="2",  # bull >0 True; bear <0 False
        rvol="0.50",  # volume_confirmed False -> bull7/bear7 both False
        adx="10",  # adx_trend_strong False -> bull8/bear8 both False
        rolling_breakout="1",  # bull9 True; bear9 (==-1) False
    )
    bar = _bar("130")
    config = _config()
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH
    score = _score(signal)
    assert score == Decimal(68)
    assert _rejection_code(signal) == REJECTION_REASON_NOT_REJECTED


# ---------------------------------------------------------------------------
# 2. Scoring formula - bear-heavy case (mirror of case 1).
# ---------------------------------------------------------------------------


def test_2_bear_heavy_case_hand_computed_score() -> None:
    """Mirror of test_1: 6/9 bearish, 1/9 bullish -> by the formula's
    own symmetry (dominant_score/separation are direction-agnostic,
    only `max`/`abs` of the two scores), the score is the SAME exact
    68, but direction is BEARISH. Proves the formula is symmetric, not
    accidentally bull-favoring."""
    feature_values = _base_feature_values(
        bullish_engulfing="1",  # the ONE true bull condition (bull cond 1)
        bearish_engulfing="1",
        body_ratio="0.50",
        rsi="90",  # bull: 90 < 80 False; bear: 90 > 20 True
        price_delta="5",  # bull: <0 False; bear: >0 True
        ema_fast="80",
        ema_slow="90",
        ema_trend="100",
        price="70",  # trend_bear: 70<100 and 80<90<100 -> True
        macd_hist="-2",  # bear <0 True
        rvol="0.50",
        adx="10",
        rolling_breakout="-1",  # bear9 True; bull9 False
    )
    bar = _bar("70")
    config = _config()
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BEARISH
    assert _score(signal) == Decimal(68)
    assert _rejection_code(signal) == REJECTION_REASON_NOT_REJECTED


# ---------------------------------------------------------------------------
# 3. Balanced/ambiguous (tie) case -> NEUTRAL, rejection reason TIE.
# ---------------------------------------------------------------------------


def test_3_balanced_tie_case_is_neutral_with_zero_separation() -> None:
    """All feature values left at `_base_feature_values()`'s defaults.
    Every gate is False EXCEPT one: the default `rsi="50"` satisfies
    BOTH the bull gate (rsi<80) AND the bear gate (rsi>20) at once (50
    is inside both ranges) - so exactly 1 of 9 conditions is True on
    EACH side (bull condition 3, bear condition 3), everything else
    (engulfing 0/0, stable_candle False at body_ratio 0.50, price_delta
    0 satisfies neither <0 nor >0, ema_fast=ema_slow=ema_trend=100 so
    neither strict trend inequality holds, macd_hist 0 satisfies
    neither >0 nor <0, rvol 0.50 keeps volume_confirmed False, adx 10
    keeps adx_trend_strong False, rolling_breakout 0 satisfies neither
    ==1 nor ==-1) is False:
        bull_score = bear_score = 1/9 * 100 = 11.11111...
        dominant_score = 11.11111...
        separation = |0| / max(22.22222, 1) * 100 = 0
        setup_quality_score = 0.72 * 100/9 + 0.28*0 = 72/9 = 8 exactly
    Direction is NEUTRAL (a tie, per `REJECTION_REASON_TIE`'s own
    docstring in the strategy module) - not a fabricated directional
    signal."""
    feature_values = _base_feature_values()  # every field at its default
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL
    # Decimal division of 1/9 is a non-terminating repeating decimal,
    # truncated at the runtime's default 28-digit context precision -
    # the true mathematical value is exactly 8, but the Decimal result
    # lands one ULP below it (7.999999999999999999999999999). Compared
    # with a tight tolerance rather than exact equality for that reason
    # alone (contrast test_1/test_2/test_3b below, where the terms
    # happen to cancel to an exact Decimal).
    assert abs(_score(signal) - Decimal(8)) < Decimal("1e-25")
    assert _rejection_code(signal) == REJECTION_REASON_TIE


def test_3b_balanced_nonzero_tie_case() -> None:
    """3/9 true on BOTH sides (via the shared `stable_candle` and
    doubly-set engulfing conditions, `rolling_breakout=0` so it does
    not break the tie - see test_4/test_5 below for the case where it
    does):
        bull_true = {bullish_engulfing, stable_candle, rsi<80(rsi=50)} = 3
        bear_true = {bearish_engulfing, stable_candle, rsi>20(rsi=50)} = 3
        bull_score = bear_score = 3/9*100 = 33.33333...
        dominant_score = 33.33333...
        separation = |0| / max(66.6667, 1) * 100 = 0
        setup_quality_score = 0.72*33.33333 + 0.28*0 = 24.0 exactly
        (0.72 * 100/3 = 72/3 = 24 exactly)
    """
    feature_values = _base_feature_values(
        bullish_engulfing="1",
        bearish_engulfing="1",
        body_ratio="0.90",  # stable_candle True (shared)
        rsi="50",  # bull: 50<80 True; bear: 50>20 True
        price_delta="0",  # neither
        macd_hist="0",  # neither
        rvol="0.50",
        adx="10",
        rolling_breakout="0",  # does not tip either side - see test_4/5
    )
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL
    assert _score(signal) == Decimal(24)
    assert _rejection_code(signal) == REJECTION_REASON_TIE


# ---------------------------------------------------------------------------
# 4/5. `rolling_breakout` genuinely changes the emitted signal.
# ---------------------------------------------------------------------------
#
# Reuses test_3b's exact 3-true/3-true tie construction (everything
# else pinned identically) and varies ONLY `rolling_breakout` - direct,
# minimal-diff behavioral proof that this new condition (BLOCKER A,
# closed at CHECKPOINT-GAINZ-B1) is a REAL scoring input, not merely
# "computed but never consulted".


def _tie_base_feature_values(rolling_breakout: str) -> dict[str, FeatureValue]:
    return _base_feature_values(
        bullish_engulfing="1",
        bearish_engulfing="1",
        body_ratio="0.90",
        rsi="50",
        price_delta="0",
        macd_hist="0",
        rvol="0.50",
        adx="10",
        rolling_breakout=rolling_breakout,
    )


def test_4_rolling_breakout_zero_leaves_the_old_condition_set_tied_neutral() -> None:
    """With `rolling_breakout=0` (neither breakout nor breakdown), the
    OLD (pre-CHECKPOINT-GAINZ-B1, 8-condition) outcome is reproduced
    exactly: bull_true=bear_true=3 (of the 8 non-breakout conditions) ->
    tie -> NEUTRAL. This is the baseline this checkpoint's wiring must
    change in the next two tests."""
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, _tie_base_feature_values("0"), config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_5_rolling_breakout_equals_1_flips_the_same_tie_to_bullish() -> None:
    """IDENTICAL feature values to test_4 except `rolling_breakout=1`
    (a genuine breakout) - this is the exact case the checkpoint
    directive requires: a bar/feature configuration that would NOT have
    produced a directional signal under the OLD condition set (test_4:
    NEUTRAL) but DOES now, purely because `rolling_breakout` is wired
    in as a real 9th condition:
        bull_true = 3 (old) + 1 (rolling_breakout==1) = 4
        bear_true = 3 (old) + 0 (rolling_breakout==-1 is False) = 3
        4 > 3 -> BULLISH (previously this exact configuration was a
        3-3 tie -> NEUTRAL, see test_4)."""
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, _tie_base_feature_values("1"), config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH
    assert _rejection_code(signal) == REJECTION_REASON_NOT_REJECTED


def test_5b_rolling_breakout_equals_negative_1_flips_the_same_tie_to_bearish() -> None:
    """Symmetric case: `rolling_breakout=-1` (a genuine breakdown) tips
    the identical test_4 tie the OTHER way:
        bull_true = 3 + 0 = 3, bear_true = 3 + 1 = 4 -> BEARISH."""
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, _tie_base_feature_values("-1"), config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BEARISH
    assert _rejection_code(signal) == REJECTION_REASON_NOT_REJECTED


def test_5c_removing_rolling_breakout_by_zeroing_it_reverts_to_neutral() -> None:
    """Inverse direction of the same proof, phrased as the directive's
    "vice versa" case: START from the BULLISH test_5 configuration,
    then zero out `rolling_breakout` (simulating "remove the condition
    set's newest member") - the signal reverts to the test_4 NEUTRAL
    tie. Confirms the dependency is exactly `rolling_breakout` and
    nothing else changed between the two evaluate() calls."""
    bar = _bar("100")
    config = _config()
    bullish_values = _tie_base_feature_values("1")
    neutral_values = dict(bullish_values)
    neutral_values[ROLLING_BREAKOUT] = _fv(ROLLING_BREAKOUT, "0")

    bullish_signal = _strategy().evaluate(bar, bullish_values, config)
    neutral_signal = _strategy().evaluate(bar, neutral_values, config)

    assert bullish_signal is not None and bullish_signal.direction is StrategyDirection.BULLISH
    assert neutral_signal is not None and neutral_signal.direction is StrategyDirection.NEUTRAL


# ---------------------------------------------------------------------------
# 6. required_features()/evaluate() wiring sanity.
# ---------------------------------------------------------------------------


def test_6_rolling_breakout_is_a_required_feature_at_the_default_lookback() -> None:
    config = _config()
    required = _strategy().required_features(config)
    assert ROLLING_BREAKOUT in required


def test_6b_missing_rolling_breakout_feature_value_yields_no_signal() -> None:
    """Warm-up/missing-data safety (existing convention, re-verified
    for the new condition): if `rolling_breakout_20` itself is missing
    from `feature_values` (e.g. insufficient warm-up upstream), the
    strategy must return `None`, never fabricate a signal that ignores
    the missing condition."""
    feature_values = _tie_base_feature_values("1")
    del feature_values[ROLLING_BREAKOUT]
    bar = _bar("100")
    config = _config()
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is None


# ---------------------------------------------------------------------------
# 7. StrategySignal schema untouched - evidence-tuple extension point only.
# ---------------------------------------------------------------------------


def test_7_evidence_carries_both_adapter_owned_fields_signal_schema_unchanged() -> None:
    bar = _bar("130")
    config = _config()
    feature_values = _base_feature_values(
        bullish_engulfing="1",
        rsi="10",
        price_delta="-5",
        ema_fast="120",
        ema_slow="110",
        ema_trend="100",
        price="130",
        macd_hist="2",
        rolling_breakout="1",
    )
    signal = _strategy().evaluate(bar, feature_values, config)
    assert signal is not None
    names = {fv.feature_name for fv in signal.evidence}
    assert SETUP_QUALITY_SCORE_FEATURE_NAME in names
    assert REJECTION_REASON_CODE_FEATURE_NAME in names
    # `StrategySignal` itself carries no new field - the frozen dataclass
    # fields are exactly the pre-existing set (Checkpoint 26 contract).
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(signal)}
    assert field_names == {
        "strategy_id",
        "specification_version",
        "code_version",
        "configuration_version",
        "instrument_id",
        "timeframe",
        "timestamp",
        "direction",
        "price",
        "evidence",
    }
    # CHECKPOINT-GAINZ-C bumped code_version again ("v2" -> "v3") when
    # adding the minimum_setup_quality_score gate - this assertion is
    # updated as the same kind of expected, documented consequence
    # CHECKPOINT-GAINZ-B1 itself already established a precedent for.
    assert signal.code_version == "v3"


# ---------------------------------------------------------------------------
# 8. code_version bump sanity.
# ---------------------------------------------------------------------------


def test_8_code_version_bumped_at_least_once_same_strategy_and_spec_identity() -> None:
    strategy = _strategy()
    assert strategy.strategy_id == STRATEGY_ID
    assert strategy.specification_version == "v1"
    # "v2" at CHECKPOINT-GAINZ-B1, "v3" at CHECKPOINT-GAINZ-C (the
    # minimum_setup_quality_score gate) - same strategy/spec identity
    # preserved across both in-place extensions.
    assert strategy.code_version == "v3"
    assert CODE_VERSION == "v3"
