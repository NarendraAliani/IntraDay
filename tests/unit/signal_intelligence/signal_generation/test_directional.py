# tests/unit/signal_intelligence/signal_generation/test_directional.py
#
# Unit tests for the Checkpoint 18 directional signal-generation rule -
# pure Python, no database, no Django, runs unconditionally.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe, Version
from intraday.signal_intelligence.signal_generation.contracts import (
    DIRECTIONAL_INDICATION_DEFINITION_NAME,
    DIRECTIONAL_INDICATION_DEFINITION_VERSION,
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.signal_generation.directional import (
    generate_directional_indication,
    generate_directional_indications,
)
from intraday.signal_intelligence.signal_generation.errors import (
    DuplicateFeatureObservationError,
    InvalidAtrValueError,
    MisalignedFeatureInstrumentError,
    MisalignedFeatureTimeframeError,
    MisalignedFeatureTimestampError,
    OutOfOrderFeatureObservationError,
    WrongFeatureTypeError,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
FEATURE_VERSION = Version(value="v1")


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


def _feature(
    name: str,
    value: str,
    *,
    offset_minutes: int = 0,
    instrument_id: InstrumentId = RELIANCE,
    timeframe: Timeframe = Timeframe.FIVE_MINUTE,
) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FEATURE_VERSION,
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=START + timedelta(minutes=5 * offset_minutes),
        value=Decimal(value),
    )


def _observation(
    *, price: str, sma: str, ema: str, atr: str, offset_minutes: int = 0
) -> tuple[Bar, FeatureValue, FeatureValue, FeatureValue]:
    bar = _bar(price, offset_minutes=offset_minutes)
    sma_value = _feature("sma_20", sma, offset_minutes=offset_minutes)
    ema_value = _feature("ema_10", ema, offset_minutes=offset_minutes)
    atr_value = _feature("atr_14", atr, offset_minutes=offset_minutes)
    return bar, sma_value, ema_value, atr_value


# ---------------------------------------------------------------------------
# Signal definition identity
# ---------------------------------------------------------------------------


def test_definition_name_and_version_are_stable_constants() -> None:
    assert DIRECTIONAL_INDICATION_DEFINITION_NAME == "sma_ema_atr_directional"
    assert Version(value="v1") == DIRECTIONAL_INDICATION_DEFINITION_VERSION


def test_indication_carries_the_definition_identity() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.definition_name == DIRECTIONAL_INDICATION_DEFINITION_NAME
    assert indication.definition_version == DIRECTIONAL_INDICATION_DEFINITION_VERSION


# ---------------------------------------------------------------------------
# Bullish
# ---------------------------------------------------------------------------


def test_bullish_when_ema_above_sma_and_price_above_ema() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.BULLISH


# ---------------------------------------------------------------------------
# Bearish
# ---------------------------------------------------------------------------


def test_bearish_when_ema_below_sma_and_price_below_ema() -> None:
    bar, sma, ema, atr = _observation(price="90", sma="100", ema="95", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.BEARISH


# ---------------------------------------------------------------------------
# Neutral
# ---------------------------------------------------------------------------


def test_neutral_when_ema_equals_sma() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="100", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.NEUTRAL


def test_neutral_when_price_equals_ema() -> None:
    bar, sma, ema, atr = _observation(price="105", sma="100", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.NEUTRAL


def test_neutral_when_price_equals_sma_but_ema_disagrees() -> None:
    # ema > sma (bullish-leaning) but price sits exactly at sma, below ema.
    bar, sma, ema, atr = _observation(price="100", sma="100", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.NEUTRAL


def test_neutral_when_ema_sma_and_price_directional_signals_disagree() -> None:
    # ema > sma (bullish-leaning) but price < ema (bearish-leaning) - conflict -> NEUTRAL.
    bar, sma, ema, atr = _observation(price="90", sma="90", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.NEUTRAL


def test_neutral_with_atr_exactly_zero_constant_market() -> None:
    bar, sma, ema, atr = _observation(price="100", sma="100", ema="100", atr="0")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.NEUTRAL
    assert indication.atr.value == Decimal("0")


# ---------------------------------------------------------------------------
# ATR validity
# ---------------------------------------------------------------------------


def test_negative_atr_rejected() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="-1")
    with pytest.raises(InvalidAtrValueError):
        generate_directional_indication(bar, sma, ema, atr)


def test_zero_atr_is_valid_and_does_not_raise() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="0")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.direction is SignalDirection.BULLISH


# ---------------------------------------------------------------------------
# Feature-type sanity checks (defense in depth)
# ---------------------------------------------------------------------------


def test_wrong_feature_type_in_sma_slot_rejected() -> None:
    bar, _sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    wrong = _feature("ema_10", "100")  # an EMA value passed where SMA is expected
    with pytest.raises(WrongFeatureTypeError):
        generate_directional_indication(bar, wrong, ema, atr)


def test_wrong_feature_type_in_atr_slot_rejected() -> None:
    bar, sma, ema, _atr = _observation(price="110", sma="100", ema="105", atr="5")
    wrong = _feature("sma_20", "5")
    with pytest.raises(WrongFeatureTypeError):
        generate_directional_indication(bar, sma, ema, wrong)


# ---------------------------------------------------------------------------
# Feature alignment
# ---------------------------------------------------------------------------


def test_mismatched_instrument_rejected() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    wrong_instrument_atr = _feature("atr_14", "5", instrument_id=TCS)
    with pytest.raises(MisalignedFeatureInstrumentError):
        generate_directional_indication(bar, sma, ema, wrong_instrument_atr)


def test_mismatched_timeframe_rejected() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    wrong_timeframe_ema = _feature("ema_10", "105", timeframe=Timeframe.ONE_MINUTE)
    with pytest.raises(MisalignedFeatureTimeframeError):
        generate_directional_indication(bar, sma, wrong_timeframe_ema, atr)


def test_mismatched_timestamp_rejected() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    wrong_timestamp_sma = _feature("sma_20", "100", offset_minutes=1)
    with pytest.raises(MisalignedFeatureTimestampError):
        generate_directional_indication(bar, wrong_timestamp_sma, ema, atr)


def test_the_exact_diagram_example_is_rejected_for_timestamp_misalignment() -> None:
    """The specific illustrative case from the checkpoint brief:
    SMA@10:15, EMA@10:16, ATR@10:14, Price@10:16 - four different
    timestamps for SMA/ATR must be rejected, never silently blended."""
    price_bar = _bar("110", offset_minutes=16)
    sma_value = _feature("sma_20", "100", offset_minutes=15)
    ema_value = _feature("ema_10", "105", offset_minutes=16)
    atr_value = _feature("atr_14", "5", offset_minutes=14)
    with pytest.raises(MisalignedFeatureTimestampError):
        generate_directional_indication(price_bar, sma_value, ema_value, atr_value)


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


def test_price_remains_decimal_never_float() -> None:
    bar, sma, ema, atr = _observation(price="110.55", sma="100.11", ema="105.33", atr="5.25")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert isinstance(indication.price, Decimal)
    assert indication.price == Decimal("110.55")
    assert isinstance(indication.sma.value, Decimal)
    assert isinstance(indication.ema.value, Decimal)
    assert isinstance(indication.atr.value, Decimal)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_indication() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    first = generate_directional_indication(bar, sma, ema, atr)
    second = generate_directional_indication(bar, sma, ema, atr)
    assert first == second


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_indication_references_the_exact_feature_inputs() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    indication = generate_directional_indication(bar, sma, ema, atr)
    assert indication.sma == sma
    assert indication.ema == ema
    assert indication.atr == atr
    assert indication.instrument_id == bar.instrument_id
    assert indication.timeframe == bar.timeframe
    assert indication.timestamp == bar.timestamp


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_source_inputs_are_not_mutated() -> None:
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    bar_before, sma_before, ema_before, atr_before = bar, sma, ema, atr
    generate_directional_indication(bar, sma, ema, atr)
    # Frozen dataclasses cannot be mutated in place - equality after the
    # call proves nothing was replaced/reassigned either.
    assert bar == bar_before
    assert sma == sma_before
    assert ema == ema_before
    assert atr == atr_before


# ---------------------------------------------------------------------------
# Series-level alignment: generate_directional_indications
# ---------------------------------------------------------------------------


def _series_observation(
    price: str, sma: str, ema: str, atr: str, offset_minutes: int
) -> tuple[Bar, FeatureValue, FeatureValue, FeatureValue]:
    return _observation(price=price, sma=sma, ema=ema, atr=atr, offset_minutes=offset_minutes)


def test_series_skips_timestamps_missing_a_required_feature_warm_up() -> None:
    bars = tuple(_bar(str(100 + i), offset_minutes=i) for i in range(5))
    # SMA only available from offset 2 onward (simulating a longer warm-up).
    sma_values = tuple(_feature("sma_20", str(100 + i), offset_minutes=i) for i in range(2, 5))
    ema_values = tuple(_feature("ema_10", str(100 + i), offset_minutes=i) for i in range(5))
    atr_values = tuple(_feature("atr_14", "5", offset_minutes=i) for i in range(5))

    indications = generate_directional_indications(bars, sma_values, ema_values, atr_values)

    assert len(indications) == 3  # only offsets 2, 3, 4 have all three features
    assert [i.timestamp for i in indications] == [
        bars[2].timestamp,
        bars[3].timestamp,
        bars[4].timestamp,
    ]


def test_series_produces_no_indications_when_a_series_is_empty() -> None:
    bars = tuple(_bar(str(100 + i), offset_minutes=i) for i in range(3))
    assert generate_directional_indications(bars, (), (), ()) == ()


def test_series_output_reflects_the_correct_direction_per_timestamp() -> None:
    bar0, sma0, ema0, atr0 = _series_observation("110", "100", "105", "5", 0)
    bar1, sma1, ema1, atr1 = _series_observation("90", "100", "95", "5", 1)
    indications = generate_directional_indications(
        (bar0, bar1), (sma0, sma1), (ema0, ema1), (atr0, atr1)
    )
    assert indications[0].direction is SignalDirection.BULLISH
    assert indications[1].direction is SignalDirection.BEARISH


def test_series_mixed_instrument_rejected() -> None:
    bars = (_bar("100", offset_minutes=0), _bar("101", offset_minutes=1, instrument_id=TCS))
    sma_values = (
        _feature("sma_20", "100", offset_minutes=0),
        _feature("sma_20", "101", offset_minutes=1),
    )
    ema_values = (
        _feature("ema_10", "100", offset_minutes=0),
        _feature("ema_10", "101", offset_minutes=1),
    )
    atr_values = (
        _feature("atr_14", "5", offset_minutes=0),
        _feature("atr_14", "5", offset_minutes=1),
    )
    with pytest.raises(MisalignedFeatureInstrumentError):
        generate_directional_indications(bars, sma_values, ema_values, atr_values)


def test_series_duplicate_feature_timestamp_rejected() -> None:
    bars = tuple(_bar(str(100 + i), offset_minutes=i) for i in range(2))
    duplicate = _feature("sma_20", "100", offset_minutes=0)
    sma_values = (duplicate, duplicate)
    ema_values = tuple(_feature("ema_10", "100", offset_minutes=i) for i in range(2))
    atr_values = tuple(_feature("atr_14", "5", offset_minutes=i) for i in range(2))
    with pytest.raises(DuplicateFeatureObservationError):
        generate_directional_indications(bars, sma_values, ema_values, atr_values)


def test_series_out_of_order_feature_input_rejected() -> None:
    bars = tuple(_bar(str(100 + i), offset_minutes=i) for i in range(2))
    sma_values = (
        _feature("sma_20", "101", offset_minutes=1),
        _feature("sma_20", "100", offset_minutes=0),
    )
    ema_values = tuple(_feature("ema_10", "100", offset_minutes=i) for i in range(2))
    atr_values = tuple(_feature("atr_14", "5", offset_minutes=i) for i in range(2))
    with pytest.raises(OutOfOrderFeatureObservationError):
        generate_directional_indications(bars, sma_values, ema_values, atr_values)


# ---------------------------------------------------------------------------
# No look-ahead
# ---------------------------------------------------------------------------


def test_appending_a_future_observation_does_not_change_earlier_indications() -> None:
    bar0, sma0, ema0, atr0 = _series_observation("110", "100", "105", "5", 0)
    bar1, sma1, ema1, atr1 = _series_observation("90", "100", "95", "5", 1)
    short = generate_directional_indications((bar0,), (sma0,), (ema0,), (atr0,))

    bar_future, sma_future, ema_future, atr_future = _series_observation("999", "1", "999", "1", 2)
    longer = generate_directional_indications(
        (bar0, bar1, bar_future),
        (sma0, sma1, sma_future),
        (ema0, ema1, ema_future),
        (atr0, atr1, atr_future),
    )

    assert short[0] == longer[0]


def test_modifying_a_future_observation_does_not_change_earlier_indications() -> None:
    bar0, sma0, ema0, atr0 = _series_observation("110", "100", "105", "5", 0)
    bar1, sma1, ema1, atr1 = _series_observation("90", "100", "95", "5", 1)

    bar2a, sma2a, ema2a, atr2a = _series_observation("200", "150", "180", "3", 2)
    bar2b, sma2b, ema2b, atr2b = _series_observation("9999", "1", "9999", "999", 2)

    variant_a = generate_directional_indications(
        (bar0, bar1, bar2a), (sma0, sma1, sma2a), (ema0, ema1, ema2a), (atr0, atr1, atr2a)
    )
    variant_b = generate_directional_indications(
        (bar0, bar1, bar2b), (sma0, sma1, sma2b), (ema0, ema1, ema2b), (atr0, atr1, atr2b)
    )

    assert variant_a[:-1] == variant_b[:-1]


@given(
    prices=st.lists(
        st.decimals(min_value="10", max_value="1000", places=2, allow_nan=False),
        min_size=2,
        max_size=15,
    ),
)
def test_property_no_future_observation_influences_earlier_indications(
    prices: list[Decimal],
) -> None:
    bars = tuple(_bar(str(p), offset_minutes=i) for i, p in enumerate(prices))
    sma_values = tuple(_feature("sma_20", str(p), offset_minutes=i) for i, p in enumerate(prices))
    ema_values = tuple(_feature("ema_10", str(p), offset_minutes=i) for i, p in enumerate(prices))
    atr_values = tuple(_feature("atr_14", "1", offset_minutes=i) for i in range(len(prices)))

    full = generate_directional_indications(bars, sma_values, ema_values, atr_values)
    prefix = generate_directional_indications(
        bars[:-1], sma_values[:-1], ema_values[:-1], atr_values[:-1]
    )

    assert prefix == full[: len(prefix)]


# ---------------------------------------------------------------------------
# Property-based: directional invariants
# ---------------------------------------------------------------------------


@given(
    sma=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    ema=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    price=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    atr=st.decimals(min_value="0", max_value="1000", places=2, allow_nan=False),
)
def test_property_bullish_iff_ema_above_sma_and_price_above_ema(
    sma: Decimal, ema: Decimal, price: Decimal, atr: Decimal
) -> None:
    bar, sma_value, ema_value, atr_value = _observation(
        price=str(price), sma=str(sma), ema=str(ema), atr=str(atr)
    )
    indication = generate_directional_indication(bar, sma_value, ema_value, atr_value)

    if ema > sma and price > ema:
        assert indication.direction is SignalDirection.BULLISH
    elif ema < sma and price < ema:
        assert indication.direction is SignalDirection.BEARISH
    else:
        assert indication.direction is SignalDirection.NEUTRAL


@given(
    sma=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    ema=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    price=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    atr=st.decimals(min_value="0", max_value="1000", places=2, allow_nan=False),
)
def test_property_determinism_holds_for_arbitrary_inputs(
    sma: Decimal, ema: Decimal, price: Decimal, atr: Decimal
) -> None:
    bar, sma_value, ema_value, atr_value = _observation(
        price=str(price), sma=str(sma), ema=str(ema), atr=str(atr)
    )
    first = generate_directional_indication(bar, sma_value, ema_value, atr_value)
    second = generate_directional_indication(bar, sma_value, ema_value, atr_value)
    assert first == second


def test_indication_construction_rejects_non_utc_naive_timestamp_indirectly() -> None:
    """Sanity check that DirectionalIndication itself still enforces UTC
    via ensure_utc - defense in depth even though every code path that
    constructs one today derives its timestamp from an already-UTC Bar."""
    bar, sma, ema, atr = _observation(price="110", sma="100", ema="105", atr="5")
    with pytest.raises(ValueError, match="must be positive"):
        DirectionalIndication(
            definition_name=DIRECTIONAL_INDICATION_DEFINITION_NAME,
            definition_version=DIRECTIONAL_INDICATION_DEFINITION_VERSION,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=SignalDirection.NEUTRAL,
            price=Decimal("-1"),
            sma=sma,
            ema=ema,
            atr=atr,
        )
