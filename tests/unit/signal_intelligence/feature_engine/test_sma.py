# tests/unit/signal_intelligence/feature_engine/test_sma.py
#
# Unit tests for the Checkpoint 15 SMA computation - pure Python, no
# database, no Django, runs unconditionally.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    InvalidLookbackError,
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)


def _bar(
    close: str,
    *,
    offset_minutes: int = 0,
    instrument_id: InstrumentId = RELIANCE,
    timeframe: Timeframe = Timeframe.FIVE_MINUTE,
) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=START + timedelta(minutes=5 * offset_minutes),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


def _series(*closes: str) -> tuple[Bar, ...]:
    return tuple(_bar(close, offset_minutes=i) for i, close in enumerate(closes))


# ---------------------------------------------------------------------------
# Feature identity
# ---------------------------------------------------------------------------


def test_sma_5_and_sma_10_have_distinct_identity() -> None:
    sma5 = SimpleMovingAverageDefinition(lookback=5)
    sma10 = SimpleMovingAverageDefinition(lookback=10)
    assert sma5.feature_name != sma10.feature_name
    assert sma5.feature_name == "sma_5"
    assert sma10.feature_name == "sma_10"


def test_same_definition_produces_equal_identity() -> None:
    a = SimpleMovingAverageDefinition(lookback=20)
    b = SimpleMovingAverageDefinition(lookback=20)
    assert a == b
    assert a.feature_name == b.feature_name
    assert a.feature_version == b.feature_version


@pytest.mark.parametrize("invalid_lookback", [0, -1, -5])
def test_invalid_lookback_rejected(invalid_lookback: int) -> None:
    with pytest.raises(InvalidLookbackError):
        SimpleMovingAverageDefinition(lookback=invalid_lookback)


def test_non_integer_lookback_rejected() -> None:
    with pytest.raises(InvalidLookbackError):
        SimpleMovingAverageDefinition(lookback=5.5)  # type: ignore[arg-type]


def test_bool_lookback_rejected() -> None:
    """`bool` is a subclass of `int` in Python - explicitly reject it so
    `SimpleMovingAverageDefinition(lookback=True)` can never silently
    mean lookback=1."""
    with pytest.raises(InvalidLookbackError):
        SimpleMovingAverageDefinition(lookback=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SMA calculation - known values, hand-computed
# ---------------------------------------------------------------------------


def test_known_3_period_sma() -> None:
    """closes: 100, 102, 104, 106, 108 -> SMA(3): 102, 104, 106."""
    bars = _series("100", "102", "104", "106", "108")
    definition = SimpleMovingAverageDefinition(lookback=3)

    values = compute_simple_moving_average(definition, bars)

    assert [v.value for v in values] == [Decimal("102"), Decimal("104"), Decimal("106")]


def test_known_5_period_sma() -> None:
    bars = _series("10", "20", "30", "40", "50", "60")
    definition = SimpleMovingAverageDefinition(lookback=5)

    values = compute_simple_moving_average(definition, bars)

    # mean(10,20,30,40,50)=30 ; mean(20,30,40,50,60)=40
    assert [v.value for v in values] == [Decimal("30"), Decimal("40")]


def test_decimal_precision_preserved_not_float() -> None:
    bars = _series("100.01", "100.02", "100.03")
    definition = SimpleMovingAverageDefinition(lookback=3)

    values = compute_simple_moving_average(definition, bars)

    assert len(values) == 1
    assert isinstance(values[0].value, Decimal)
    assert values[0].value == Decimal("100.02")


def test_first_valid_value_occurs_only_after_n_observations() -> None:
    bars = _series("100", "101", "102")  # only 3 bars, lookback 5
    definition = SimpleMovingAverageDefinition(lookback=5)

    values = compute_simple_moving_average(definition, bars)

    assert values == ()


def test_output_is_chronologically_ordered() -> None:
    bars = _series("100", "101", "102", "103", "104")
    definition = SimpleMovingAverageDefinition(lookback=2)

    values = compute_simple_moving_average(definition, bars)

    timestamps = [v.timestamp for v in values]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


def test_zero_bars_produces_no_values() -> None:
    definition = SimpleMovingAverageDefinition(lookback=5)
    assert compute_simple_moving_average(definition, ()) == ()


def test_fewer_than_n_bars_produces_no_values() -> None:
    bars = _series("100", "101", "102", "103")  # 4 bars, lookback 5
    definition = SimpleMovingAverageDefinition(lookback=5)
    assert compute_simple_moving_average(definition, bars) == ()


def test_exactly_n_bars_produces_exactly_one_value() -> None:
    bars = _series("100", "102", "104", "106", "108")  # 5 bars, lookback 5
    definition = SimpleMovingAverageDefinition(lookback=5)

    values = compute_simple_moving_average(definition, bars)

    assert len(values) == 1
    assert values[0].value == Decimal("104")


def test_n_plus_one_bars_produces_exactly_two_values() -> None:
    bars = _series("100", "102", "104", "106", "108", "110")  # 6 bars, lookback 5
    definition = SimpleMovingAverageDefinition(lookback=5)

    values = compute_simple_moving_average(definition, bars)

    assert len(values) == 2


# ---------------------------------------------------------------------------
# Look-ahead safety
# ---------------------------------------------------------------------------


def test_future_bar_does_not_influence_earlier_output() -> None:
    short_series = _series("100", "102", "104")
    longer_series = short_series + (_bar("999", offset_minutes=3),)
    definition = SimpleMovingAverageDefinition(lookback=3)

    short_values = compute_simple_moving_average(definition, short_series)
    longer_values = compute_simple_moving_average(definition, longer_series)

    # The one value produced by the short series must be identical to the
    # corresponding (first) value produced by the longer series - the
    # extra future bar must not have changed it.
    assert short_values[0] == longer_values[0]


def test_modifying_a_future_bar_does_not_change_earlier_sma_values() -> None:
    definition = SimpleMovingAverageDefinition(lookback=2)
    base = _series("100", "102", "104")
    variant_a = base + (_bar("200", offset_minutes=3),)
    variant_b = base + (_bar("9999", offset_minutes=3),)

    values_a = compute_simple_moving_average(definition, variant_a)
    values_b = compute_simple_moving_average(definition, variant_b)

    # Every output whose timestamp precedes the differing final bar must
    # be byte-identical between the two variants.
    assert values_a[:-1] == values_b[:-1]


# ---------------------------------------------------------------------------
# Instrument integrity
# ---------------------------------------------------------------------------


def test_bars_from_different_instruments_rejected() -> None:
    bars = (
        _bar("100", offset_minutes=0, instrument_id=RELIANCE),
        _bar("101", offset_minutes=1, instrument_id=TCS),
    )
    definition = SimpleMovingAverageDefinition(lookback=2)

    with pytest.raises(MixedInstrumentSeriesError):
        compute_simple_moving_average(definition, bars)


def test_feature_output_retains_correct_instrument_identity() -> None:
    bars = _series("100", "102", "104")  # default instrument_id is RELIANCE
    definition = SimpleMovingAverageDefinition(lookback=3)

    values = compute_simple_moving_average(definition, bars)

    assert values[0].instrument_id == RELIANCE


# ---------------------------------------------------------------------------
# Timeframe integrity
# ---------------------------------------------------------------------------


def test_timeframe_is_retained_on_output() -> None:
    bars = _series("100", "102", "104")
    definition = SimpleMovingAverageDefinition(lookback=3)

    values = compute_simple_moving_average(definition, bars)

    assert values[0].timeframe == Timeframe.FIVE_MINUTE


def test_mixed_timeframe_input_rejected() -> None:
    bars = (
        _bar("100", offset_minutes=0, timeframe=Timeframe.FIVE_MINUTE),
        _bar("101", offset_minutes=1, timeframe=Timeframe.ONE_MINUTE),
    )
    definition = SimpleMovingAverageDefinition(lookback=2)

    with pytest.raises(MixedTimeframeSeriesError):
        compute_simple_moving_average(definition, bars)


# ---------------------------------------------------------------------------
# Market-data integrity (reused from Checkpoint 14, not reimplemented)
# ---------------------------------------------------------------------------


def test_duplicate_bar_timestamps_rejected() -> None:
    duplicate = _bar("100", offset_minutes=0)
    bars = (duplicate, duplicate)
    definition = SimpleMovingAverageDefinition(lookback=2)

    with pytest.raises(DuplicateBarTimestampError):
        compute_simple_moving_average(definition, bars)


def test_out_of_order_bars_rejected() -> None:
    bars = (_bar("100", offset_minutes=1), _bar("101", offset_minutes=0))
    definition = SimpleMovingAverageDefinition(lookback=2)

    with pytest.raises(OutOfOrderBarError):
        compute_simple_moving_average(definition, bars)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_input_produces_identical_output() -> None:
    bars = _series("100", "102", "104", "106", "108")
    definition = SimpleMovingAverageDefinition(lookback=3)

    first = compute_simple_moving_average(definition, bars)
    second = compute_simple_moving_average(definition, bars)

    assert first == second


def test_repeated_calculation_produces_identical_decimal_values() -> None:
    bars = _series("100.111", "102.222", "104.333", "106.444")
    definition = SimpleMovingAverageDefinition(lookback=2)

    first = compute_simple_moving_average(definition, bars)
    second = compute_simple_moving_average(definition, bars)

    assert [v.value for v in first] == [v.value for v in second]
    for value in first:
        assert isinstance(value.value, Decimal)


# ---------------------------------------------------------------------------
# Property-based testing
# ---------------------------------------------------------------------------


@given(
    closes=st.lists(
        st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
        min_size=1,
        max_size=25,
    ),
    lookback=st.integers(min_value=1, max_value=10),
)
def test_every_sma_value_is_the_mean_of_exactly_lookback_preceding_closes(
    closes: list[Decimal], lookback: int
) -> None:
    bars = tuple(_bar(str(close), offset_minutes=i) for i, close in enumerate(closes))
    definition = SimpleMovingAverageDefinition(lookback=lookback)

    values = compute_simple_moving_average(definition, bars)

    for index, value in enumerate(values):
        # The i-th output corresponds to bars[lookback - 1 + i]; its
        # window is exactly the `lookback` closes ending there.
        window_end = lookback + index
        window = closes[window_end - lookback : window_end]
        assert value.value == sum(window) / lookback
        assert value.timestamp == bars[window_end - 1].timestamp


@given(
    closes=st.lists(
        st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
        min_size=2,
        max_size=25,
    ),
    lookback=st.integers(min_value=1, max_value=10),
)
def test_no_output_uses_future_observations(closes: list[Decimal], lookback: int) -> None:
    full_bars = tuple(_bar(str(close), offset_minutes=i) for i, close in enumerate(closes))
    prefix_bars = full_bars[:-1]
    definition = SimpleMovingAverageDefinition(lookback=lookback)

    full_values = compute_simple_moving_average(definition, full_bars)
    prefix_values = compute_simple_moving_average(definition, prefix_bars)

    # Every value the shorter (prefix) series produced must appear
    # unchanged among the longer series' values - trimming the future
    # bar never altered an already-computed value.
    assert prefix_values == full_values[: len(prefix_values)]
