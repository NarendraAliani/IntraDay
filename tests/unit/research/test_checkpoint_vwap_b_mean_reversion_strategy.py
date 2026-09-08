# tests/unit/research/test_checkpoint_vwap_b_mean_reversion_strategy.py
#
# CHECKPOINT-VWAP-B: unit tests for `VwapMeanReversionStrategy` -
# entry/exit logic against constructed feature values, matching the
# fixture style `test_checkpoint_64_99_gainz_research_adapter.py`
# established (`_bar()`/`_config()` helpers, direct `evaluate()`/
# `build_trade_plan()` calls against hand-built `feature_values` dicts,
# no full feature-series computation needed for these unit-level
# cases). Phase B of `VWAP_STRATEGY_ROADMAP.md` - `registry.py` and
# every other strategy file (including `gainz_compatible_research.py`,
# still paused) untouched.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
)
from intraday.trading_engine.strategy_execution.strategies.vwap_mean_reversion import (
    DEVIATION_MULTIPLE_FEATURE_NAME,
    STOP_PRICE_FEATURE_NAME,
    STRATEGY_ID,
    TARGET_PRICE_FEATURE_NAME,
    VwapMeanReversionStrategy,
)

INSTRUMENT = InstrumentId("NSE:VWAPTEST")
TF = Timeframe.FIVE_MINUTE
TS = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
FV_VERSION = Version(value="v1")


def _bar(close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=TF,
        timestamp=TS,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


def _feature(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FV_VERSION,
        instrument_id=INSTRUMENT,
        timeframe=TF,
        timestamp=TS,
        value=Decimal(value),
    )


def _strategy() -> VwapMeanReversionStrategy:
    return VwapMeanReversionStrategy()


def _config(**overrides: object) -> StrategyConfigurationValues:
    strategy = _strategy()
    values: dict[str, object] = {}
    for p in strategy.parameter_schema().parameters:
        if p.default is not None:
            values[p.parameter_id] = p.default
    values.update(overrides)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", "v1", "v1", values)


# ---------------------------------------------------------------------------
# 1. parameter_schema() / required_features()
# ---------------------------------------------------------------------------


def test_1_parameter_schema_has_exactly_4_parameters() -> None:
    schema = _strategy().parameter_schema()
    assert len(schema.parameters) == 4
    ids = {p.parameter_id for p in schema.parameters}
    assert ids == {
        "vwap_deviation_atr_multiplier",
        "stop_loss_atr_multiplier",
        "atr_lookback",
        "target_reversion_fraction",
    }


def test_2_required_features_are_vwap_and_atr_no_suffix_on_vwap() -> None:
    config = _config(atr_lookback=14)
    features = _strategy().required_features(config)
    assert features == ("vwap", "atr_14")


def test_2b_required_features_atr_suffix_follows_configured_lookback() -> None:
    config = _config(atr_lookback=21)
    features = _strategy().required_features(config)
    assert features == ("vwap", "atr_21")


# ---------------------------------------------------------------------------
# 2. evaluate() - clear BUY / SELL / no-signal / warmup cases.
# ---------------------------------------------------------------------------


def test_3_clear_buy_price_below_vwap_by_more_than_n_atr() -> None:
    # vwap=100, atr=2, N=1.5 -> deviation_band=3 -> trigger below 97.
    # price=96 is 2 ATR below vwap (96 < 100-3=97) -> BULLISH.
    config = _config(vwap_deviation_atr_multiplier=Decimal("1.5"))
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH
    assert signal.price == Decimal("96")


def test_4_clear_sell_price_above_vwap_by_more_than_n_atr() -> None:
    # price=105 is above vwap+3=103 -> BEARISH.
    config = _config(vwap_deviation_atr_multiplier=Decimal("1.5"))
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("105"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BEARISH


def test_5_in_band_price_produces_neutral_not_none() -> None:
    # price=98 is within [97, 103] -> NEUTRAL (a real signal object, not
    # a warmup None - matching ema_crossover's own NEUTRAL-is-a-value
    # convention).
    config = _config(vwap_deviation_atr_multiplier=Decimal("1.5"))
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("98"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_6_exact_boundary_is_not_yet_a_trigger() -> None:
    # price == vwap - deviation_band EXACTLY (97) is NOT "< 97" - still
    # NEUTRAL. Strict inequality, not >=/<=.
    config = _config(vwap_deviation_atr_multiplier=Decimal("1.5"))
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("97"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_7_missing_vwap_feature_returns_none_warmup() -> None:
    config = _config()
    feature_values = {"atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("96"), feature_values, config)
    assert signal is None


def test_8_missing_atr_feature_returns_none_warmup() -> None:
    config = _config()
    feature_values = {"vwap": _feature("vwap", "100")}
    signal = _strategy().evaluate(_bar("96"), feature_values, config)
    assert signal is None


def test_9_empty_feature_values_returns_none() -> None:
    signal = _strategy().evaluate(_bar("96"), {}, _config())
    assert signal is None


# ---------------------------------------------------------------------------
# 3. evidence tuple - auditable, matches the checkpoint's own instruction.
# ---------------------------------------------------------------------------


def test_10_evidence_always_includes_vwap_atr_and_deviation_multiple() -> None:
    config = _config(vwap_deviation_atr_multiplier=Decimal("1.5"))
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    # NEUTRAL case - target/stop evidence should be ABSENT, but vwap/atr/
    # deviation multiple must still be present.
    signal = _strategy().evaluate(_bar("98"), feature_values, config)
    assert signal is not None
    names = {e.feature_name for e in signal.evidence}
    assert "vwap" in names
    assert "atr_14" in names
    assert DEVIATION_MULTIPLE_FEATURE_NAME in names
    assert TARGET_PRICE_FEATURE_NAME not in names
    assert STOP_PRICE_FEATURE_NAME not in names

    deviation = next(e for e in signal.evidence if e.feature_name == DEVIATION_MULTIPLE_FEATURE_NAME)
    # (98-100)/2 = -1.0
    assert deviation.value == Decimal("-1.0")


def test_11_evidence_includes_target_and_stop_price_only_for_non_neutral() -> None:
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("2.5"),
        target_reversion_fraction=Decimal("1.0"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    signal = _strategy().evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH
    names = {e.feature_name for e in signal.evidence}
    assert TARGET_PRICE_FEATURE_NAME in names
    assert STOP_PRICE_FEATURE_NAME in names

    target = next(e for e in signal.evidence if e.feature_name == TARGET_PRICE_FEATURE_NAME)
    stop = next(e for e in signal.evidence if e.feature_name == STOP_PRICE_FEATURE_NAME)
    # target = entry + 1.0*(vwap-entry) = 96 + (100-96) = 100 (== vwap, fraction=1.0)
    assert target.value == Decimal("100")
    # stop = entry - (+1)*2.5*2 = 96 - 5 = 91
    assert stop.value == Decimal("91")


# ---------------------------------------------------------------------------
# 4. build_trade_plan() - single target, entry/target/stop arithmetic.
# ---------------------------------------------------------------------------


def test_12_build_trade_plan_bullish_single_target_no_t2_t3() -> None:
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("2.5"),
        target_reversion_fraction=Decimal("1.0"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("96"), feature_values, config, signal)
    assert plan is not None
    assert plan.entry_price == Decimal("96")
    assert plan.target_1 == Decimal("100")  # == vwap, fraction=1.0
    assert plan.stop_loss == Decimal("91")  # 96 - 2.5*2
    assert plan.target_2 is None
    assert plan.target_3 is None
    assert plan.trailing_stop_loss is None


def test_13_build_trade_plan_bearish_stop_is_above_entry() -> None:
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("2.5"),
        target_reversion_fraction=Decimal("1.0"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("105"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BEARISH
    plan = strategy.build_trade_plan(_bar("105"), feature_values, config, signal)
    assert plan is not None
    assert plan.entry_price == Decimal("105")
    assert plan.target_1 == Decimal("100")  # == vwap
    assert plan.stop_loss == Decimal("110")  # 105 - (-1)*2.5*2 = 105+5


def test_14_partial_reversion_fraction_targets_closer_to_entry_not_vwap() -> None:
    # fraction=0.5: target = 96 + 0.5*(100-96) = 98, NOT vwap (100).
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("2.5"),
        target_reversion_fraction=Decimal("0.5"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("96"), feature_values, config, signal)
    assert plan is not None
    assert plan.target_1 == Decimal("98")


def test_15_build_trade_plan_returns_none_for_neutral_signal() -> None:
    config = _config()
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("98"), feature_values, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL
    plan = strategy.build_trade_plan(_bar("98"), feature_values, config, signal)
    assert plan is None


# ---------------------------------------------------------------------------
# 5. The M > N cross-parameter guard - the honest finding, tested directly.
# ---------------------------------------------------------------------------


def test_16_stop_multiplier_equal_to_deviation_refuses_plan() -> None:
    # M == N (both 1.5) - degenerate, must refuse rather than produce a
    # stop at the exact same distance as the entry trigger.
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("1.5"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("96"), feature_values, config, signal)
    assert plan is None


def test_17_stop_multiplier_less_than_deviation_refuses_plan() -> None:
    # M < N (M=1.0, N=1.5) - stop would sit INSIDE the entry trigger
    # distance, immediately breached - must refuse.
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("1.0"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("96"), feature_values, config, signal)
    assert plan is None


def test_18_stop_multiplier_greater_than_deviation_produces_a_plan() -> None:
    # M > N (M=2.5, N=1.5) - the normal, valid case (already exercised
    # in test_12, re-asserted here explicitly as the counterpart to
    # test_16/17's refusal cases).
    config = _config(
        vwap_deviation_atr_multiplier=Decimal("1.5"),
        stop_loss_atr_multiplier=Decimal("2.5"),
    )
    feature_values = {"vwap": _feature("vwap", "100"), "atr_14": _feature("atr_14", "2")}
    strategy = _strategy()
    signal = strategy.evaluate(_bar("96"), feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("96"), feature_values, config, signal)
    assert plan is not None
