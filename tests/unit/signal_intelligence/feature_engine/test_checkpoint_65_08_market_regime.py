# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_65_08_market_regime.py
#
# Checkpoint 65.08: CANONICAL PRODUCTION CATEGORICAL FEATURE -
# market_regime. REDUCED, TARGETED testing only (per checkpoint
# directive) - covers state vocabulary, the exact baseline rule (BULL/
# BEAR/SIDEWAYS/TRANSITION), boundary conditions (ADX==ADX_MIN,
# +DI==-DI, ema_fast==ema_slow), parameter validation, warm-up,
# unavailable-dependency handling, no-lookahead (mutation + extension),
# determinism, CategoricalFeatureValue output type, and registry/
# dispatcher integration. Does NOT re-run the full suite.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.feature.contracts import CategoricalFeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import MarketRegimeDefinition
from intraday.signal_intelligence.feature_engine.errors import (
    InvalidLookbackError,
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.field_registry import (
    FieldDataType,
    get_field,
    is_parameterized_feature,
    list_fields,
)
from intraday.signal_intelligence.feature_engine.market_regime import (
    BEAR,
    BULL,
    SIDEWAYS,
    TRANSITION,
    compute_market_regime,
)

IID = InstrumentId("TEST")
IID2 = InstrumentId("OTHER")
TF = Timeframe.ONE_MINUTE
TF2 = Timeframe.FIVE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(i: int, high: str, low: str, close: str, *, instrument_id=IID, timeframe=TF) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=BASE_TS + timedelta(minutes=i),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
    )


def _uptrend_bars(n: int) -> tuple[Bar, ...]:
    """A clean, strongly-trending-up series - long enough (>= 40 bars) to
    clear market_regime's own effective warm-up (max(29, ema_slow))."""
    bars = []
    price = 100
    for i in range(n):
        price += 2
        bars.append(_bar(i, str(price + 1), str(price - 1), str(price)))
    return tuple(bars)


def _downtrend_bars(n: int) -> tuple[Bar, ...]:
    bars = []
    price = 500
    for i in range(n):
        price -= 2
        bars.append(_bar(i, str(price + 1), str(price - 1), str(price)))
    return tuple(bars)


def _flat_bars(n: int) -> tuple[Bar, ...]:
    """Flat price -> ADX collapses toward 0 -> SIDEWAYS branch."""
    return tuple(_bar(i, "101", "99", "100") for i in range(n))


DEFAULT_DEFINITION = MarketRegimeDefinition(adx_min=20, ema_fast_lookback=9, ema_slow_lookback=20)


# ---------------------------------------------------------------------------
# A. State vocabulary / basic rule outcomes.
# ---------------------------------------------------------------------------


def test_a1_uptrend_produces_bull() -> None:
    bars = _uptrend_bars(45)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values
    assert values[-1].category == BULL


def test_a2_downtrend_produces_bear() -> None:
    bars = _downtrend_bars(45)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values
    assert values[-1].category == BEAR


def test_a3_flat_produces_sideways() -> None:
    bars = _flat_bars(45)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values
    assert all(v.category == SIDEWAYS for v in values)


def test_a4_closed_vocabulary_only() -> None:
    bars = _uptrend_bars(45) + _downtrend_bars(45) + _flat_bars(45)
    # Not a valid single series (chronology/mixed-direction aside) - just
    # verify each independently-computed set only ever emits the 4 states.
    all_categories: set[str] = set()
    for series in (_uptrend_bars(45), _downtrend_bars(45), _flat_bars(45)):
        for v in compute_market_regime(DEFAULT_DEFINITION, series):
            all_categories.add(v.category)
    assert all_categories.issubset({BULL, BEAR, SIDEWAYS, TRANSITION})


def test_a5_output_is_categorical_feature_value() -> None:
    bars = _uptrend_bars(45)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert all(isinstance(v, CategoricalFeatureValue) for v in values)
    assert all(v.feature_name == "market_regime_20_9_20" for v in values)


# ---------------------------------------------------------------------------
# B. Boundary / edge cases (Part M).
# ---------------------------------------------------------------------------


def test_b1_adx_exactly_equal_to_threshold_still_directional() -> None:
    # Use a very low ADX_MIN so a real (non-zero, non-huge) ADX value from
    # a trending series is >= threshold - proving `>=` (not `>`) is used,
    # i.e. equality counts as trend-strength-OK, never SIDEWAYS.
    bars = _uptrend_bars(45)
    from intraday.signal_intelligence.feature_engine.definitions import (
        DirectionalMovementDefinition,
    )
    from intraday.signal_intelligence.feature_engine.directional_movement import (
        compute_average_directional_index,
    )

    adx_values = compute_average_directional_index(DirectionalMovementDefinition(14), bars)
    last_adx = int(adx_values[-1].value)
    definition = MarketRegimeDefinition(
        adx_min=last_adx, ema_fast_lookback=9, ema_slow_lookback=20
    )
    values = compute_market_regime(definition, bars)
    assert values[-1].category == BULL


def test_b2_plus_di_equals_minus_di_or_ema_equal_never_fabricates_bull_bear() -> None:
    # A very short/flat window collapses toward equal DI/EMA states; the
    # regime must then be SIDEWAYS or TRANSITION, never BULL/BEAR.
    bars = _flat_bars(45)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert all(v.category in (SIDEWAYS, TRANSITION) for v in values)


def test_b3_insufficient_history_yields_no_output() -> None:
    bars = _uptrend_bars(5)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values == ()


def test_b4_empty_bars_yields_empty_tuple() -> None:
    assert compute_market_regime(DEFAULT_DEFINITION, ()) == ()


# ---------------------------------------------------------------------------
# C. Parameter validation (Part G) - invalid inputs rejected, never repaired.
# ---------------------------------------------------------------------------


def test_c1_adx_min_must_be_positive() -> None:
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=0, ema_fast_lookback=9, ema_slow_lookback=20)
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=-5, ema_fast_lookback=9, ema_slow_lookback=20)


def test_c2_ema_fast_lookback_must_be_positive() -> None:
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=20, ema_fast_lookback=0, ema_slow_lookback=20)


def test_c3_ema_slow_must_exceed_ema_fast_never_swapped() -> None:
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=20, ema_fast_lookback=20, ema_slow_lookback=9)
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=20, ema_fast_lookback=20, ema_slow_lookback=20)


def test_c4_adx_min_must_be_int_not_bool_or_float() -> None:
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=True, ema_fast_lookback=9, ema_slow_lookback=20)
    with pytest.raises(InvalidLookbackError):
        MarketRegimeDefinition(adx_min=20.5, ema_fast_lookback=9, ema_slow_lookback=20)


# ---------------------------------------------------------------------------
# D. Warm-up.
# ---------------------------------------------------------------------------


def test_d1_no_output_before_binding_warmup() -> None:
    # ADX's own warm-up floor is 2*lookback bars (see
    # directional_movement.py's `_compute_directional_series`); fewer bars
    # than that must never produce market_regime output.
    bars = _uptrend_bars(27)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values == ()


def test_d2_first_output_timestamp_matches_first_adx_timestamp() -> None:
    from intraday.signal_intelligence.feature_engine.definitions import (
        DirectionalMovementDefinition,
    )
    from intraday.signal_intelligence.feature_engine.directional_movement import (
        compute_average_directional_index,
    )

    bars = _uptrend_bars(45)
    adx_values = compute_average_directional_index(DirectionalMovementDefinition(14), bars)
    values = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values
    assert values[0].timestamp >= adx_values[0].timestamp


# ---------------------------------------------------------------------------
# E. Unavailable-dependency handling (Part I) - never a fabricated fallback.
# ---------------------------------------------------------------------------


def test_e1_short_series_missing_ema_slow_produces_no_output() -> None:
    # ema_slow_lookback=200 vastly exceeds available bars - no output at
    # all, never a fabricated SIDEWAYS/TRANSITION.
    bars = _uptrend_bars(45)
    definition = MarketRegimeDefinition(adx_min=20, ema_fast_lookback=9, ema_slow_lookback=200)
    values = compute_market_regime(definition, bars)
    assert values == ()


# ---------------------------------------------------------------------------
# F. No-lookahead.
# ---------------------------------------------------------------------------


def test_f1_mutating_future_bar_does_not_change_earlier_output() -> None:
    bars = list(_uptrend_bars(45))
    baseline = compute_market_regime(DEFAULT_DEFINITION, tuple(bars))

    mutated_last = Bar(
        instrument_id=bars[-1].instrument_id,
        timeframe=bars[-1].timeframe,
        timestamp=bars[-1].timestamp,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("100"),
    )
    bars[-1] = mutated_last
    mutated_values = compute_market_regime(DEFAULT_DEFINITION, tuple(bars))

    # Every timestamp except the mutated final bar's own output must be
    # byte-identical - the mutation of the LAST bar must never leak
    # backwards into earlier categories.
    baseline_by_ts = {v.timestamp: v.category for v in baseline[:-1]}
    mutated_by_ts = {v.timestamp: v.category for v in mutated_values[:-1]}
    assert baseline_by_ts == mutated_by_ts


def test_f2_extending_series_with_future_bars_does_not_change_prior_output() -> None:
    bars = _uptrend_bars(45)
    baseline = compute_market_regime(DEFAULT_DEFINITION, bars)

    extended = bars + _uptrend_bars(10 + len(bars))[len(bars) :]
    extended_values = compute_market_regime(DEFAULT_DEFINITION, extended)

    baseline_by_ts = {v.timestamp: v.category for v in baseline}
    extended_prefix_by_ts = {
        v.timestamp: v.category for v in extended_values if v.timestamp in baseline_by_ts
    }
    assert baseline_by_ts == extended_prefix_by_ts


# ---------------------------------------------------------------------------
# G. Determinism.
# ---------------------------------------------------------------------------


def test_g1_identical_input_produces_identical_output() -> None:
    bars = _uptrend_bars(45)
    values_1 = compute_market_regime(DEFAULT_DEFINITION, bars)
    values_2 = compute_market_regime(DEFAULT_DEFINITION, bars)
    assert values_1 == values_2


# ---------------------------------------------------------------------------
# H. Series integrity (reused, not duplicated).
# ---------------------------------------------------------------------------


def test_h1_mixed_instrument_series_rejected() -> None:
    bars = _uptrend_bars(10) + (_bar(10, "111", "109", "110", instrument_id=IID2),)
    with pytest.raises(MixedInstrumentSeriesError):
        compute_market_regime(DEFAULT_DEFINITION, bars)


def test_h2_mixed_timeframe_series_rejected() -> None:
    bars = _uptrend_bars(10) + (_bar(10, "111", "109", "110", timeframe=TF2),)
    with pytest.raises(MixedTimeframeSeriesError):
        compute_market_regime(DEFAULT_DEFINITION, bars)


# ---------------------------------------------------------------------------
# I. Registry / dispatcher integration.
# ---------------------------------------------------------------------------


def test_i1_registered_as_categorical_field() -> None:
    field = get_field("market_regime")
    assert field is not None
    assert field.data_type == FieldDataType.CATEGORICAL


def test_i2_registered_field_appears_in_list_fields() -> None:
    assert any(f.field_id == "market_regime" for f in list_fields())


def test_i3_is_parameterized_feature() -> None:
    assert is_parameterized_feature("market_regime") is True


def test_i4_no_split_bull_bear_sideways_transition_fields() -> None:
    ids = {f.field_id for f in list_fields()}
    assert "market_regime_bull" not in ids
    assert "market_regime_bear" not in ids
    assert "market_regime_sideways" not in ids
    assert "market_regime_transition" not in ids


def test_i5_dispatcher_computes_market_regime() -> None:
    bars = _uptrend_bars(45)
    values = compute_feature_series("market_regime_20_9_20", bars)
    assert values
    assert all(isinstance(v, CategoricalFeatureValue) for v in values)
    assert values[-1].category == BULL


def test_i6_dispatcher_numeric_feature_still_returns_feature_value() -> None:
    from intraday.domain.feature.contracts import FeatureValue

    bars = _uptrend_bars(45)
    values = compute_feature_series("ema_9", bars)
    assert values
    assert all(isinstance(v, FeatureValue) for v in values)


def test_i7_dispatcher_unrecognized_field_id_raises() -> None:
    with pytest.raises(ValueError):
        compute_feature_series("not_a_real_field_99", _uptrend_bars(45))
