# tests/unit/research/test_checkpoint_orb_b_breakout_strategy.py
#
# CHECKPOINT-ORB-B: unit tests for `OrbBreakoutStrategy` - entry/exit
# logic against constructed feature values, matching the fixture style
# `test_checkpoint_vwap_b_mean_reversion_strategy.py` established.
# Phase B of `ORB_STRATEGY_ROADMAP.md` - `registry.py` and every other
# strategy file untouched.
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
from intraday.trading_engine.strategy_execution.strategies.orb_breakout import (
    BREAKOUT_DISTANCE_FEATURE_NAME,
    RANGE_SIZE_FEATURE_NAME,
    STOP_PRICE_FEATURE_NAME,
    STRATEGY_ID,
    TARGET_PRICE_FEATURE_NAME,
    OrbBreakoutStrategy,
)

INSTRUMENT = InstrumentId("NSE:ORBTEST")
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


def _strategy() -> OrbBreakoutStrategy:
    return OrbBreakoutStrategy()


def _config(**overrides: object) -> StrategyConfigurationValues:
    strategy = _strategy()
    values: dict[str, object] = {}
    for p in strategy.parameter_schema().parameters:
        if p.default is not None:
            values[p.parameter_id] = p.default
    values.update(overrides)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", "v1", "v1", values)


_RANGE = {
    "opening_range_high_15": _feature("opening_range_high_15", "110"),
    "opening_range_low_15": _feature("opening_range_low_15", "100"),
}


# ---------------------------------------------------------------------------
# 1. parameter_schema() / required_features()
# ---------------------------------------------------------------------------


def test_1_parameter_schema_has_exactly_5_parameters() -> None:
    schema = _strategy().parameter_schema()
    assert len(schema.parameters) == 5
    ids = {p.parameter_id for p in schema.parameters}
    assert ids == {
        "opening_range_minutes",
        "target_range_multiplier",
        "stop_range_fraction",
        "minimum_range_atr_multiplier",
        "atr_lookback",
    }


def test_2_required_features_use_orb_a_exact_field_id_shape() -> None:
    config = _config(opening_range_minutes=15)
    features = _strategy().required_features(config)
    assert features == ("opening_range_high_15", "opening_range_low_15")


def test_2b_required_features_follow_configured_window() -> None:
    config = _config(opening_range_minutes=30)
    features = _strategy().required_features(config)
    assert features == ("opening_range_high_30", "opening_range_low_30")


def test_2c_atr_only_required_when_filter_enabled() -> None:
    disabled = _config(minimum_range_atr_multiplier=Decimal("0"))
    assert _strategy().required_features(disabled) == (
        "opening_range_high_15",
        "opening_range_low_15",
    )
    enabled = _config(minimum_range_atr_multiplier=Decimal("0.5"), atr_lookback=14)
    assert _strategy().required_features(enabled) == (
        "opening_range_high_15",
        "opening_range_low_15",
        "atr_14",
    )


# ---------------------------------------------------------------------------
# 2. evaluate() - clear BUY / SELL / no-signal / warmup cases.
# ---------------------------------------------------------------------------


def test_3_clear_buy_price_closes_above_range_high() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("112"), _RANGE, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH
    assert signal.price == Decimal("112")


def test_4_clear_sell_price_closes_below_range_low() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("97"), _RANGE, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BEARISH


def test_5_inside_the_range_is_neutral_not_none() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("105"), _RANGE, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_6_exact_boundary_is_not_yet_a_breakout() -> None:
    # close == range_high EXACTLY (110) is NOT "> 110" - still NEUTRAL.
    config = _config()
    signal = _strategy().evaluate(_bar("110"), _RANGE, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_7_missing_range_features_returns_none_warmup() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("112"), {}, config)
    assert signal is None


def test_7b_only_one_of_high_low_present_returns_none() -> None:
    config = _config()
    signal = _strategy().evaluate(
        _bar("112"), {"opening_range_high_15": _RANGE["opening_range_high_15"]}, config
    )
    assert signal is None


# ---------------------------------------------------------------------------
# 3. The ATR filter - both filtered-out and pass-through cases.
# ---------------------------------------------------------------------------


def test_8_filter_disabled_by_default_narrow_range_still_breaks_out() -> None:
    narrow_range = {
        "opening_range_high_15": _feature("opening_range_high_15", "100.1"),
        "opening_range_low_15": _feature("opening_range_low_15", "100.0"),
    }
    config = _config()  # minimum_range_atr_multiplier=0 (default) -> disabled
    signal = _strategy().evaluate(_bar("100.2"), narrow_range, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH


def test_9_filter_enabled_narrow_range_gets_filtered_to_neutral() -> None:
    # range_size = 0.1, atr = 10 -> minimum required = 0.5*10 = 5. 0.1 < 5 -> filtered.
    narrow_range = {
        "opening_range_high_15": _feature("opening_range_high_15", "100.1"),
        "opening_range_low_15": _feature("opening_range_low_15", "100.0"),
        "atr_14": _feature("atr_14", "10"),
    }
    config = _config(minimum_range_atr_multiplier=Decimal("0.5"), atr_lookback=14)
    signal = _strategy().evaluate(_bar("100.2"), narrow_range, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL


def test_10_filter_enabled_wide_range_passes_through() -> None:
    # range_size = 10 (100..110), atr = 10 -> minimum required = 0.5*10 = 5. 10 >= 5 -> passes.
    wide_range = {
        "opening_range_high_15": _feature("opening_range_high_15", "110"),
        "opening_range_low_15": _feature("opening_range_low_15", "100"),
        "atr_14": _feature("atr_14", "10"),
    }
    config = _config(minimum_range_atr_multiplier=Decimal("0.5"), atr_lookback=14)
    signal = _strategy().evaluate(_bar("112"), wide_range, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.BULLISH


def test_11_filter_enabled_but_atr_not_warmed_up_returns_none() -> None:
    config = _config(minimum_range_atr_multiplier=Decimal("0.5"), atr_lookback=14)
    signal = _strategy().evaluate(_bar("112"), _RANGE, config)  # no atr_14 in feature_values
    assert signal is None


# ---------------------------------------------------------------------------
# 4. evidence tuple - auditable.
# ---------------------------------------------------------------------------


def test_12_evidence_always_includes_range_high_and_low() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("105"), _RANGE, config)  # NEUTRAL case
    assert signal is not None
    names = {e.feature_name for e in signal.evidence}
    assert "opening_range_high_15" in names
    assert "opening_range_low_15" in names
    assert RANGE_SIZE_FEATURE_NAME not in names  # only attached for non-NEUTRAL


def test_13_evidence_includes_range_size_and_breakout_distance_for_non_neutral() -> None:
    config = _config()
    signal = _strategy().evaluate(_bar("112"), _RANGE, config)
    assert signal is not None
    names = {e.feature_name for e in signal.evidence}
    assert RANGE_SIZE_FEATURE_NAME in names
    assert BREAKOUT_DISTANCE_FEATURE_NAME in names
    assert TARGET_PRICE_FEATURE_NAME in names
    assert STOP_PRICE_FEATURE_NAME in names

    range_size = next(e for e in signal.evidence if e.feature_name == RANGE_SIZE_FEATURE_NAME)
    assert range_size.value == Decimal(10)  # 110 - 100
    distance = next(
        e for e in signal.evidence if e.feature_name == BREAKOUT_DISTANCE_FEATURE_NAME
    )
    # (112-110)/10 = 0.2
    assert distance.value == Decimal("0.2")


# ---------------------------------------------------------------------------
# 5. build_trade_plan() - single target, entry/target/stop arithmetic.
# ---------------------------------------------------------------------------


def test_14_build_trade_plan_bullish_stop_at_opposite_boundary_default() -> None:
    config = _config(target_range_multiplier=Decimal("1.0"), stop_range_fraction=Decimal("1.0"))
    strategy = _strategy()
    signal = strategy.evaluate(_bar("112"), _RANGE, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("112"), _RANGE, config, signal)
    assert plan is not None
    assert plan.entry_price == Decimal("112")
    # target = 112 + 1.0*10 = 122
    assert plan.target_1 == Decimal("122")
    # stop_range_fraction=1.0 -> stop == opposite boundary == range_low == 100
    assert plan.stop_loss == Decimal("100")
    assert plan.target_2 is None
    assert plan.target_3 is None


def test_15_build_trade_plan_bearish_stop_at_opposite_boundary() -> None:
    config = _config(target_range_multiplier=Decimal("1.0"), stop_range_fraction=Decimal("1.0"))
    strategy = _strategy()
    signal = strategy.evaluate(_bar("97"), _RANGE, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("97"), _RANGE, config, signal)
    assert plan is not None
    # target = 97 - 1.0*10 = 87
    assert plan.target_1 == Decimal("87")
    # stop == opposite boundary == range_high == 110
    assert plan.stop_loss == Decimal("110")


def test_16_tighter_stop_fraction_moves_stop_inside_the_range() -> None:
    # fraction=0.5 -> BULLISH stop = range_high - 0.5*10 = 105 (midpoint), not range_low (100).
    config = _config(target_range_multiplier=Decimal("1.0"), stop_range_fraction=Decimal("0.5"))
    strategy = _strategy()
    signal = strategy.evaluate(_bar("112"), _RANGE, config)
    assert signal is not None
    plan = strategy.build_trade_plan(_bar("112"), _RANGE, config, signal)
    assert plan is not None
    assert plan.stop_loss == Decimal("105")


def test_17_build_trade_plan_returns_none_for_neutral_signal() -> None:
    config = _config()
    strategy = _strategy()
    signal = strategy.evaluate(_bar("105"), _RANGE, config)
    assert signal is not None
    assert signal.direction is StrategyDirection.NEUTRAL
    plan = strategy.build_trade_plan(_bar("105"), _RANGE, config, signal)
    assert plan is None


def test_18_stop_always_stays_on_the_correct_side_of_entry_by_construction() -> None:
    # Structural safety property (module docstring's own claim, tested
    # directly): for ANY valid stop_range_fraction in (0, 1], the
    # BULLISH stop must be strictly below entry, and the BEARISH stop
    # strictly above - no parameter combination can violate this.
    strategy = _strategy()
    for fraction in (Decimal("0.01"), Decimal("0.5"), Decimal("1.0")):
        config = _config(stop_range_fraction=fraction)
        bull_signal = strategy.evaluate(_bar("112"), _RANGE, config)
        assert bull_signal is not None
        bull_plan = strategy.build_trade_plan(_bar("112"), _RANGE, config, bull_signal)
        assert bull_plan is not None
        assert bull_plan.stop_loss < bull_plan.entry_price

        bear_signal = strategy.evaluate(_bar("97"), _RANGE, config)
        assert bear_signal is not None
        bear_plan = strategy.build_trade_plan(_bar("97"), _RANGE, config, bear_signal)
        assert bear_plan is not None
        assert bear_plan.stop_loss > bear_plan.entry_price
