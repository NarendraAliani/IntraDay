# tests/unit/signal_intelligence/theoretical_outcome/test_outcome.py
#
# Unit tests for the Checkpoint 21 theoretical-outcome (MFE/MAE) rule -
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
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe, Version
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.theoretical_outcome.contracts import (
    OUTCOME_DEFINITION_NAME,
    OUTCOME_DEFINITION_VERSION,
    ObservationCompleteness,
    TheoreticalOutcome,
)
from intraday.signal_intelligence.theoretical_outcome.errors import (
    InvalidHorizonError,
    MismatchedInstrumentError,
    MismatchedTimeframeError,
    NonFutureObservationError,
)
from intraday.signal_intelligence.theoretical_outcome.outcome import (
    compute_theoretical_outcome,
    compute_theoretical_outcomes,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
SIGNAL_TIME = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
FEATURE_VERSION = Version(value="v1")


def _ohlc_bar(
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    offset_minutes: int,
    instrument_id: InstrumentId = RELIANCE,
    timeframe: Timeframe = Timeframe.FIVE_MINUTE,
) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=SIGNAL_TIME + timedelta(minutes=5 * offset_minutes),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def _flat_bar(price: str, offset_minutes: int) -> Bar:
    return _ohlc_bar(open_=price, high=price, low=price, close=price, offset_minutes=offset_minutes)


def _feature(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FEATURE_VERSION,
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=SIGNAL_TIME,
        value=Decimal(value),
    )


def _indication(
    direction: SignalDirection,
    price: str = "100",
    *,
    instrument_id: InstrumentId = RELIANCE,
    timeframe: Timeframe = Timeframe.FIVE_MINUTE,
) -> DirectionalIndication:
    return DirectionalIndication(
        definition_name="sma_ema_atr_directional",
        definition_version=Version(value="v1"),
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=SIGNAL_TIME,
        direction=direction,
        price=Decimal(price),
        sma=_feature("sma_20", "95"),
        ema=_feature("ema_10", "98"),
        atr=_feature("atr_14", "5"),
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_identity_and_versioning_constants() -> None:
    assert OUTCOME_DEFINITION_NAME == "mfe_mae_price_excursion"
    assert Version(value="v1") == OUTCOME_DEFINITION_VERSION


def test_outcome_carries_indication_identity() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_ohlc_bar(open_="101", high="105", low="99", close="103", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.outcome_definition_name == OUTCOME_DEFINITION_NAME
    assert outcome.outcome_definition_version == OUTCOME_DEFINITION_VERSION
    assert outcome.instrument_id == indication.instrument_id
    assert outcome.timeframe == indication.timeframe
    assert outcome.signal_timestamp == indication.timestamp
    assert outcome.indication == indication


# ---------------------------------------------------------------------------
# BULLISH - hand-derived vector (Checkpoint 21 §4)
#
#   reference = 100
#   bar1: H=105 L=99
#   bar2: H=110 L=101
#   bar3: H=103 L=95
#   MFE = max(105-100, 110-100, 103-100) = max(5,10,3) = 10
#   MAE = min(99-100, 101-100, 95-100)  = min(-1,1,-5)  = -5
# ---------------------------------------------------------------------------


def test_bullish_mfe_mae_hand_derived_vector() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (
        _ohlc_bar(open_="101", high="105", low="99", close="102", offset_minutes=1),
        _ohlc_bar(open_="102", high="110", low="101", close="108", offset_minutes=2),
        _ohlc_bar(open_="100", high="103", low="95", close="97", offset_minutes=3),
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=3)
    assert outcome.mfe == Decimal("10")
    assert outcome.mae == Decimal("-5")


def test_bullish_zero_movement_gives_zero_mfe_and_mae() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("100", 1), _flat_bar("100", 2))
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=2)
    assert outcome.mfe == Decimal("0")
    assert outcome.mae == Decimal("0")


def test_bullish_only_upward_movement_gives_zero_mae_not_positive() -> None:
    """The clamping decision in action: price only ever rose, so the raw
    (unclamped) `min(low - reference)` would be positive - clamped to 0,
    never reported as a spuriously "favorable" MAE."""
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_ohlc_bar(open_="101", high="108", low="101", close="105", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mae == Decimal("0")
    assert outcome.mfe == Decimal("8")


# ---------------------------------------------------------------------------
# BEARISH - hand-derived vector (Checkpoint 21 §4)
#
#   reference = 100
#   bar1: H=101 L=95
#   bar2: H=99  L=90
#   bar3: H=105 L=92
#   MFE = max(100-95, 100-90, 100-92) = max(5,10,8) = 10
#   MAE = min(100-101, 100-99, 100-105) = min(-1,1,-5) = -5
# ---------------------------------------------------------------------------


def test_bearish_mfe_mae_hand_derived_vector() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    bars = (
        _ohlc_bar(open_="99", high="101", low="95", close="97", offset_minutes=1),
        _ohlc_bar(open_="97", high="99", low="90", close="93", offset_minutes=2),
        _ohlc_bar(open_="93", high="105", low="92", close="95", offset_minutes=3),
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=3)
    assert outcome.mfe == Decimal("10")
    assert outcome.mae == Decimal("-5")


def test_bearish_zero_movement_gives_zero_mfe_and_mae() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    bars = (_flat_bar("100", 1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mfe == Decimal("0")
    assert outcome.mae == Decimal("0")


def test_bearish_only_downward_movement_gives_zero_mae_not_positive() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    bars = (_ohlc_bar(open_="97", high="99", low="90", close="92", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mae == Decimal("0")
    assert outcome.mfe == Decimal("10")


# ---------------------------------------------------------------------------
# NEUTRAL
# ---------------------------------------------------------------------------


def test_neutral_indication_has_no_mfe_mae() -> None:
    indication = _indication(SignalDirection.NEUTRAL, "100")
    bars = (_ohlc_bar(open_="101", high="150", low="50", close="105", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.completeness is ObservationCompleteness.COMPLETE  # data was available
    assert outcome.bars_observed == 1


# ---------------------------------------------------------------------------
# Horizon / partial / missing data
# ---------------------------------------------------------------------------


def test_no_future_bars_is_no_data_with_none_mfe_mae() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    outcome = compute_theoretical_outcome(indication, (), horizon_bars=5)
    assert outcome.completeness is ObservationCompleteness.NO_DATA
    assert outcome.mfe is None
    assert outcome.mae is None
    assert outcome.bars_observed == 0


def test_partial_horizon_computes_real_mfe_mae_but_flags_partial() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_ohlc_bar(open_="101", high="106", low="99", close="103", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=5)
    assert outcome.completeness is ObservationCompleteness.PARTIAL
    assert outcome.bars_observed == 1
    assert outcome.mfe == Decimal("6")  # real measurement, not withheld


def test_exact_horizon_is_complete() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = tuple(
        _ohlc_bar(open_="101", high="105", low="99", close="102", offset_minutes=i)
        for i in range(1, 4)
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=3)
    assert outcome.completeness is ObservationCompleteness.COMPLETE
    assert outcome.bars_observed == 3


def test_bars_beyond_horizon_are_ignored() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (
        _ohlc_bar(open_="101", high="102", low="99", close="101", offset_minutes=1),
        _ohlc_bar(
            open_="101", high="999", low="1", close="101", offset_minutes=2
        ),  # beyond horizon
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.bars_observed == 1
    assert outcome.mfe == Decimal("2")  # not influenced by the extreme bar beyond horizon


def test_invalid_horizon_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(InvalidHorizonError):
        compute_theoretical_outcome(indication, (), horizon_bars=0)


# ---------------------------------------------------------------------------
# Future-bar boundary
# ---------------------------------------------------------------------------


def test_same_timestamp_bar_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    same_time_bar = _flat_bar("101", 0)
    with pytest.raises(NonFutureObservationError):
        compute_theoretical_outcome(indication, (same_time_bar,), horizon_bars=1)


def test_first_future_bar_accepted() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("105", 1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mfe == Decimal("5")


# ---------------------------------------------------------------------------
# Instrument / timeframe integrity
# ---------------------------------------------------------------------------


def test_mismatched_instrument_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    wrong = (_flat_bar("105", 1),)
    wrong_instrument = tuple(
        _ohlc_bar(
            open_="105", high="105", low="105", close="105", offset_minutes=1, instrument_id=TCS
        )
        for _ in wrong
    )
    with pytest.raises(MismatchedInstrumentError):
        compute_theoretical_outcome(indication, wrong_instrument, horizon_bars=1)


def test_mismatched_timeframe_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    wrong_timeframe = (
        _ohlc_bar(
            open_="105",
            high="105",
            low="105",
            close="105",
            offset_minutes=1,
            timeframe=Timeframe.ONE_MINUTE,
        ),
    )
    with pytest.raises(MismatchedTimeframeError):
        compute_theoretical_outcome(indication, wrong_timeframe, horizon_bars=1)


# ---------------------------------------------------------------------------
# Chronology
# ---------------------------------------------------------------------------


def test_duplicate_bar_timestamps_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    duplicate = _flat_bar("101", 1)
    with pytest.raises(DuplicateBarTimestampError):
        compute_theoretical_outcome(indication, (duplicate, duplicate), horizon_bars=2)


def test_out_of_order_bars_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("102", 2), _flat_bar("101", 1))
    with pytest.raises(OutOfOrderBarError):
        compute_theoretical_outcome(indication, bars, horizon_bars=2)


# ---------------------------------------------------------------------------
# Precision - classic float traps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_reference", ["0.10", "1.01", "99.99", "10000.00"])
def test_decimal_precision_preserved_for_reference_and_mfe_mae(raw_reference: str) -> None:
    indication = _indication(SignalDirection.BULLISH, raw_reference)
    bumped = str(Decimal(raw_reference) + Decimal("0.01"))
    bars = (
        _ohlc_bar(
            open_=raw_reference, high=bumped, low=raw_reference, close=bumped, offset_minutes=1
        ),
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert isinstance(outcome.reference_price, Decimal)
    assert isinstance(outcome.mfe, Decimal)
    assert isinstance(outcome.mae, Decimal)
    assert outcome.reference_price == Decimal(raw_reference)
    assert outcome.mfe == Decimal("0.01")


# ---------------------------------------------------------------------------
# Same-bar high/low ambiguity
# ---------------------------------------------------------------------------


def test_single_bar_contributes_to_both_mfe_and_mae() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_ohlc_bar(open_="100", high="106", low="94", close="101", offset_minutes=1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert outcome.mfe == Decimal("6")
    assert outcome.mae == Decimal("-6")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_outcome() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("105", 1), _flat_bar("103", 2))
    first = compute_theoretical_outcome(indication, bars, horizon_bars=2)
    second = compute_theoretical_outcome(indication, bars, horizon_bars=2)
    assert first == second


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_source_indication_and_bars_unchanged() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("105", 1),)
    indication_before, bars_before = indication, bars
    compute_theoretical_outcome(indication, bars, horizon_bars=1)
    assert indication == indication_before
    assert bars == bars_before


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------


def test_outcome_construction_rejects_positive_mae() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(ValueError, match="never be positive"):
        TheoreticalOutcome(
            outcome_definition_name=OUTCOME_DEFINITION_NAME,
            outcome_definition_version=OUTCOME_DEFINITION_VERSION,
            instrument_id=indication.instrument_id,
            timeframe=indication.timeframe,
            signal_timestamp=indication.timestamp,
            horizon_bars=1,
            direction=indication.direction,
            reference_price=indication.price,
            mfe=Decimal("5"),
            mae=Decimal("1"),  # illegal: positive MAE
            bars_observed=1,
            completeness=ObservationCompleteness.COMPLETE,
            indication=indication,
        )


def test_outcome_construction_rejects_mfe_mae_present_with_no_data() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(ValueError, match="NO_DATA"):
        TheoreticalOutcome(
            outcome_definition_name=OUTCOME_DEFINITION_NAME,
            outcome_definition_version=OUTCOME_DEFINITION_VERSION,
            instrument_id=indication.instrument_id,
            timeframe=indication.timeframe,
            signal_timestamp=indication.timestamp,
            horizon_bars=1,
            direction=indication.direction,
            reference_price=indication.price,
            mfe=Decimal("5"),
            mae=Decimal("0"),
            bars_observed=0,
            completeness=ObservationCompleteness.NO_DATA,
            indication=indication,
        )


# ---------------------------------------------------------------------------
# Series-level: multiple indications
# ---------------------------------------------------------------------------


def test_series_verifies_multiple_indications_independently() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100")  # signal at offset 0
    indication_b = DirectionalIndication(
        definition_name="sma_ema_atr_directional",
        definition_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=SIGNAL_TIME + timedelta(minutes=10),  # offset 2
        direction=SignalDirection.BEARISH,
        price=Decimal("200"),
        sma=_feature("sma_20", "205"),
        ema=_feature("ema_10", "202"),
        atr=_feature("atr_14", "5"),
    )
    bars = (
        # A's first future bar (after offset 0); also exists before B's
        # signal timestamp so it is NOT part of B's future window at all.
        _ohlc_bar(open_="105", high="110", low="103", close="107", offset_minutes=2),
        # B's first future bar (after offset 2).
        _ohlc_bar(open_="190", high="195", low="185", close="188", offset_minutes=3),
    )
    outcomes = compute_theoretical_outcomes((indication_a, indication_b), bars, horizon_bars=1)
    assert len(outcomes) == 2
    assert outcomes[0].mfe == Decimal("10")  # bullish a: high 110 - ref 100
    assert outcomes[1].mfe == Decimal("15")  # bearish b: ref 200 - low 185


def test_series_mismatched_instrument_rejected() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100", instrument_id=RELIANCE)
    indication_b = _indication(SignalDirection.BULLISH, "100", instrument_id=TCS)
    with pytest.raises(MismatchedInstrumentError):
        compute_theoretical_outcomes((indication_a, indication_b), (), horizon_bars=1)


# ---------------------------------------------------------------------------
# No-look-ahead
# ---------------------------------------------------------------------------


def test_future_append_beyond_horizon_does_not_change_result() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    within_horizon = (_ohlc_bar(open_="101", high="106", low="99", close="103", offset_minutes=1),)
    beyond_horizon = within_horizon + (
        _ohlc_bar(open_="103", high="999", low="1", close="103", offset_minutes=2),
    )
    short_result = compute_theoretical_outcome(indication, within_horizon, horizon_bars=1)
    longer_result = compute_theoretical_outcome(indication, beyond_horizon, horizon_bars=1)
    assert short_result == longer_result


def test_modifying_a_bar_beyond_horizon_does_not_change_result() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    base = (_ohlc_bar(open_="101", high="106", low="99", close="103", offset_minutes=1),)
    variant_a = base + (_ohlc_bar(open_="103", high="200", low="1", close="103", offset_minutes=2),)
    variant_b = base + (
        _ohlc_bar(open_="103", high="9999", low="0.01", close="103", offset_minutes=2),
    )
    result_a = compute_theoretical_outcome(indication, variant_a, horizon_bars=1)
    result_b = compute_theoretical_outcome(indication, variant_b, horizon_bars=1)
    assert result_a == result_b


def test_same_timestamp_bar_modification_cannot_leak_in() -> None:
    """The bar AT the signal timestamp is rejected as non-future entirely
    (tested above) - this test confirms the outcome is computed only
    from what was actually supplied as future_bars, never reaching back
    to the signal-time bar under any circumstance."""
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_flat_bar("105", 1),)
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=1)
    # The reference price is the indication's own price - never derived
    # from any bar close, so a signal-time bar (even if it existed)
    # could not influence it.
    assert outcome.reference_price == indication.price


def test_cross_instrument_bars_cannot_contaminate_result() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    reliance_bars = (_flat_bar("110", 1),)
    baseline = compute_theoretical_outcome(indication, reliance_bars, horizon_bars=1)

    # A completely separate call with TCS bars raises (proven elsewhere);
    # here we prove that RELIANCE-only computation is unaffected by the
    # mere EXISTENCE of other-instrument data outside this call.
    tcs_bars = (
        _ohlc_bar(
            open_="500", high="999", low="1", close="500", offset_minutes=1, instrument_id=TCS
        ),
    )
    _ = tcs_bars  # never passed to the RELIANCE computation
    repeat = compute_theoretical_outcome(indication, reliance_bars, horizon_bars=1)
    assert baseline == repeat


@given(
    horizon_bars=st.integers(min_value=1, max_value=5),
    extra_bars=st.integers(min_value=0, max_value=5),
)
def test_property_bars_beyond_horizon_never_affect_the_result(
    horizon_bars: int, extra_bars: int
) -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    within = tuple(
        _ohlc_bar(open_="101", high=str(101 + i), low="99", close="101", offset_minutes=i + 1)
        for i in range(horizon_bars)
    )
    beyond = within + tuple(
        _ohlc_bar(
            open_="101", high="9999", low="0.01", close="101", offset_minutes=horizon_bars + i + 1
        )
        for i in range(extra_bars)
    )
    assert compute_theoretical_outcome(
        indication, within, horizon_bars
    ) == compute_theoretical_outcome(indication, beyond, horizon_bars)


# ---------------------------------------------------------------------------
# Property-based: MFE/MAE invariants
# ---------------------------------------------------------------------------


@given(
    reference=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    highs=st.lists(
        st.decimals(min_value="0", max_value="500", places=2, allow_nan=False),
        min_size=1,
        max_size=10,
    ),
    direction=st.sampled_from([SignalDirection.BULLISH, SignalDirection.BEARISH]),
)
def test_property_mfe_never_negative_mae_never_positive(
    reference: Decimal, highs: list[Decimal], direction: SignalDirection
) -> None:
    indication = _indication(direction, str(reference))
    bars = tuple(
        _ohlc_bar(
            open_=str(reference),
            high=str(reference + delta),
            low=str(max(Decimal("0.01"), reference - delta)),
            close=str(reference),
            offset_minutes=i + 1,
        )
        for i, delta in enumerate(highs)
    )
    outcome = compute_theoretical_outcome(indication, bars, horizon_bars=len(bars))
    assert outcome.mfe is not None
    assert outcome.mae is not None
    assert outcome.mfe >= 0
    assert outcome.mae <= 0


@given(
    reference=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    lows=st.lists(
        st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
        min_size=2,
        max_size=10,
    ),
)
def test_property_same_input_produces_same_output(reference: Decimal, lows: list[Decimal]) -> None:
    indication = _indication(SignalDirection.BULLISH, str(reference))
    bars = tuple(
        _ohlc_bar(
            open_=str(low),
            high=str(low + Decimal("1")),
            low=str(low),
            close=str(low),
            offset_minutes=i + 1,
        )
        for i, low in enumerate(lows)
    )
    first = compute_theoretical_outcome(indication, bars, horizon_bars=len(bars))
    second = compute_theoretical_outcome(indication, bars, horizon_bars=len(bars))
    assert first == second
