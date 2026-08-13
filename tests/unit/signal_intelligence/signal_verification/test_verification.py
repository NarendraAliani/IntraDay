# tests/unit/signal_intelligence/signal_verification/test_verification.py
#
# Unit tests for the Checkpoint 19 signal-verification rule - pure
# Python, no database, no Django, runs unconditionally.
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
from intraday.signal_intelligence.signal_verification.contracts import (
    VERIFICATION_DEFINITION_NAME,
    VERIFICATION_DEFINITION_VERSION,
    VerificationOutcome,
    VerificationResult,
)
from intraday.signal_intelligence.signal_verification.errors import (
    InvalidHorizonError,
    MismatchedInstrumentError,
    MismatchedTimeframeError,
    NonFutureObservationError,
)
from intraday.signal_intelligence.signal_verification.verification import (
    verify_directional_indication,
    verify_directional_indications,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
FEATURE_VERSION = Version(value="v1")


def _bar(
    close: str,
    *,
    offset_minutes: int,
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


def _feature(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FEATURE_VERSION,
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=START,
        value=Decimal(value),
    )


def _indication(
    direction: SignalDirection,
    price: str = "100",
    *,
    instrument_id: InstrumentId = RELIANCE,
    timeframe: Timeframe = Timeframe.FIVE_MINUTE,
    offset_minutes: int = 0,
) -> DirectionalIndication:
    signal_time = START + timedelta(minutes=5 * offset_minutes)
    return DirectionalIndication(
        definition_name="sma_ema_atr_directional",
        definition_version=Version(value="v1"),
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=signal_time,
        direction=direction,
        price=Decimal(price),
        sma=FeatureValue(
            feature_name="sma_20",
            feature_version=FEATURE_VERSION,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=signal_time,
            value=Decimal("100"),
        ),
        ema=FeatureValue(
            feature_name="ema_10",
            feature_version=FEATURE_VERSION,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=signal_time,
            value=Decimal("100"),
        ),
        atr=FeatureValue(
            feature_name="atr_14",
            feature_version=FEATURE_VERSION,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=signal_time,
            value=Decimal("5"),
        ),
    )


def _future_bars(*closes: str, instrument_id: InstrumentId = RELIANCE) -> tuple[Bar, ...]:
    return tuple(
        _bar(close, offset_minutes=i + 1, instrument_id=instrument_id)
        for i, close in enumerate(closes)
    )


# ---------------------------------------------------------------------------
# Outcome - bullish
# ---------------------------------------------------------------------------


def test_bullish_supported_when_price_rises() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101", "102", "105")
    result = verify_directional_indication(indication, future, horizon_bars=3)
    assert result.outcome is VerificationOutcome.SUPPORTED
    assert result.observed_price == Decimal("105")


def test_bullish_not_supported_when_price_falls() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("99", "98", "95")
    result = verify_directional_indication(indication, future, horizon_bars=3)
    assert result.outcome is VerificationOutcome.NOT_SUPPORTED


def test_bullish_not_supported_when_price_unchanged() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("100")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.outcome is VerificationOutcome.NOT_SUPPORTED


# ---------------------------------------------------------------------------
# Outcome - bearish
# ---------------------------------------------------------------------------


def test_bearish_supported_when_price_falls() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    future = _future_bars("99", "97", "95")
    result = verify_directional_indication(indication, future, horizon_bars=3)
    assert result.outcome is VerificationOutcome.SUPPORTED
    assert result.observed_price == Decimal("95")


def test_bearish_not_supported_when_price_rises() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    future = _future_bars("101", "103", "105")
    result = verify_directional_indication(indication, future, horizon_bars=3)
    assert result.outcome is VerificationOutcome.NOT_SUPPORTED


def test_bearish_not_supported_when_price_unchanged() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    future = _future_bars("100")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.outcome is VerificationOutcome.NOT_SUPPORTED


# ---------------------------------------------------------------------------
# Outcome - neutral
# ---------------------------------------------------------------------------


def test_neutral_is_always_inconclusive_never_not_supported() -> None:
    indication = _indication(SignalDirection.NEUTRAL, "100")
    future = _future_bars("50")  # even a huge move must not matter
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.observed_price is None
    assert result.evaluation_timestamp is None


# ---------------------------------------------------------------------------
# Temporal boundary
# ---------------------------------------------------------------------------


def test_future_bar_at_signal_timestamp_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    same_time_bar = _bar("101", offset_minutes=0)
    with pytest.raises(NonFutureObservationError):
        verify_directional_indication(indication, (same_time_bar,), horizon_bars=1)


def test_past_bar_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100", offset_minutes=5)
    past_bar = _bar("99", offset_minutes=0)
    with pytest.raises(NonFutureObservationError):
        verify_directional_indication(indication, (past_bar,), horizon_bars=1)


def test_correct_future_bar_accepted() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("110")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.outcome is VerificationOutcome.SUPPORTED


# ---------------------------------------------------------------------------
# Instrument / timeframe alignment
# ---------------------------------------------------------------------------


def test_mismatched_instrument_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    wrong_instrument_bar = _future_bars("101", instrument_id=TCS)
    with pytest.raises(MismatchedInstrumentError):
        verify_directional_indication(indication, wrong_instrument_bar, horizon_bars=1)


def test_mismatched_timeframe_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    wrong_timeframe_bar = (_bar("101", offset_minutes=1, timeframe=Timeframe.ONE_MINUTE),)
    with pytest.raises(MismatchedTimeframeError):
        verify_directional_indication(indication, wrong_timeframe_bar, horizon_bars=1)


# ---------------------------------------------------------------------------
# Horizon completion
# ---------------------------------------------------------------------------


def test_invalid_horizon_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(InvalidHorizonError):
        verify_directional_indication(indication, (), horizon_bars=0)


def test_negative_horizon_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(InvalidHorizonError):
        verify_directional_indication(indication, (), horizon_bars=-1)


def test_no_future_bars_is_inconclusive() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    result = verify_directional_indication(indication, (), horizon_bars=5)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_insufficient_future_bars_is_inconclusive() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101", "102")  # only 2, horizon requires 5
    result = verify_directional_indication(indication, future, horizon_bars=5)
    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_exactly_sufficient_bars_completes_horizon() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101", "102", "103")
    result = verify_directional_indication(indication, future, horizon_bars=3)
    assert result.outcome is not VerificationOutcome.INCONCLUSIVE
    assert result.observed_price == Decimal("103")


def test_extra_bars_beyond_horizon_are_ignored() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101", "102", "999", "999", "999")  # horizon=3 -> uses "102"
    result = verify_directional_indication(indication, future, horizon_bars=2)
    assert result.observed_price == Decimal("102")


# ---------------------------------------------------------------------------
# Price precision
# ---------------------------------------------------------------------------


def test_prices_remain_decimal_never_float() -> None:
    indication = _indication(SignalDirection.BULLISH, "100.55")
    future = _future_bars("101.33")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert isinstance(result.reference_price, Decimal)
    assert isinstance(result.observed_price, Decimal)
    assert result.reference_price == Decimal("100.55")
    assert result.observed_price == Decimal("101.33")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_result() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101", "102")
    first = verify_directional_indication(indication, future, horizon_bars=2)
    second = verify_directional_indication(indication, future, horizon_bars=2)
    assert first == second


# ---------------------------------------------------------------------------
# Immutability / no leakage into signal generation
# ---------------------------------------------------------------------------


def test_directional_indication_unchanged_after_verification() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    before = indication
    future = _future_bars("101")
    verify_directional_indication(indication, future, horizon_bars=1)
    assert indication == before  # frozen dataclass - structurally proven unmutated


def test_verification_result_does_not_mutate_the_embedded_indication_fields() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    future = _future_bars("101")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.indication is indication
    assert result.indication.direction is SignalDirection.BULLISH  # unchanged


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_result_carries_full_provenance() -> None:
    indication = _indication(SignalDirection.BEARISH, "100")
    future = _future_bars("95")
    result = verify_directional_indication(indication, future, horizon_bars=1)
    assert result.verification_definition_name == VERIFICATION_DEFINITION_NAME
    assert result.verification_definition_version == VERIFICATION_DEFINITION_VERSION
    assert result.instrument_id == indication.instrument_id
    assert result.timeframe == indication.timeframe
    assert result.signal_timestamp == indication.timestamp
    assert result.horizon_bars == 1
    assert result.direction == indication.direction
    assert result.reference_price == indication.price
    assert result.indication == indication
    assert result.evaluation_timestamp == future[0].timestamp


# ---------------------------------------------------------------------------
# Series-level verification (multiple signals)
# ---------------------------------------------------------------------------


def test_multiple_signals_verified_independently() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100", offset_minutes=0)
    indication_b = _indication(SignalDirection.BEARISH, "200", offset_minutes=1)
    bars = (
        _bar("100", offset_minutes=0),
        _bar("200", offset_minutes=1),
        _bar("105", offset_minutes=2),  # 1 bar after A, supports BULLISH A
        _bar("195", offset_minutes=3),  # 1 bar after B, supports BEARISH B
    )

    results = verify_directional_indications((indication_a, indication_b), bars, horizon_bars=1)

    assert len(results) == 2
    assert results[0].outcome is VerificationOutcome.SUPPORTED
    assert results[0].indication == indication_a
    assert results[1].outcome is VerificationOutcome.SUPPORTED
    assert results[1].indication == indication_b


def test_series_preserves_input_order() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100", offset_minutes=0)
    indication_b = _indication(SignalDirection.BULLISH, "100", offset_minutes=1)
    bars = (
        _bar("100", offset_minutes=0),
        _bar("100", offset_minutes=1),
        _bar("110", offset_minutes=2),
        _bar("120", offset_minutes=3),
    )
    results = verify_directional_indications((indication_b, indication_a), bars, horizon_bars=1)
    assert results[0].signal_timestamp == indication_b.timestamp
    assert results[1].signal_timestamp == indication_a.timestamp


def test_series_mismatched_instrument_rejected() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100", instrument_id=RELIANCE)
    indication_b = _indication(SignalDirection.BULLISH, "100", instrument_id=TCS, offset_minutes=1)
    with pytest.raises(MismatchedInstrumentError):
        verify_directional_indications((indication_a, indication_b), (), horizon_bars=1)


def test_series_duplicate_bar_timestamps_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    duplicate = _bar("101", offset_minutes=1)
    with pytest.raises(DuplicateBarTimestampError):
        verify_directional_indications((indication,), (duplicate, duplicate), horizon_bars=1)


def test_series_out_of_order_bars_rejected() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    bars = (_bar("102", offset_minutes=2), _bar("101", offset_minutes=1))
    with pytest.raises(OutOfOrderBarError):
        verify_directional_indications((indication,), bars, horizon_bars=1)


# ---------------------------------------------------------------------------
# No leakage across signals: verification for T does not affect
# verification for another signal, and does not affect signal generation.
# ---------------------------------------------------------------------------


def test_verifying_one_indication_does_not_affect_another_signals_result() -> None:
    indication_a = _indication(SignalDirection.BULLISH, "100", offset_minutes=0)
    indication_b = _indication(SignalDirection.BULLISH, "100", offset_minutes=0)  # identical
    future_a = _future_bars("110")
    future_b = _future_bars("90")  # different future for an otherwise-identical signal

    result_a = verify_directional_indication(indication_a, future_a, horizon_bars=1)
    result_b = verify_directional_indication(indication_b, future_b, horizon_bars=1)

    assert result_a.outcome is VerificationOutcome.SUPPORTED
    assert result_b.outcome is VerificationOutcome.NOT_SUPPORTED
    # And re-verifying A again afterward is unaffected by B ever happening.
    result_a_again = verify_directional_indication(indication_a, future_a, horizon_bars=1)
    assert result_a_again == result_a


# ---------------------------------------------------------------------------
# VerificationResult contract validation
# ---------------------------------------------------------------------------


def test_result_construction_rejects_supported_without_observed_price() -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    with pytest.raises(ValueError, match="observed_price"):
        VerificationResult(
            verification_definition_name=VERIFICATION_DEFINITION_NAME,
            verification_definition_version=VERIFICATION_DEFINITION_VERSION,
            instrument_id=indication.instrument_id,
            timeframe=indication.timeframe,
            signal_timestamp=indication.timestamp,
            horizon_bars=1,
            direction=indication.direction,
            reference_price=indication.price,
            observed_price=None,
            evaluation_timestamp=None,
            outcome=VerificationOutcome.SUPPORTED,
            indication=indication,
        )


# ---------------------------------------------------------------------------
# Property-based testing
# ---------------------------------------------------------------------------


@given(
    reference=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    observed=st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
    direction=st.sampled_from([SignalDirection.BULLISH, SignalDirection.BEARISH]),
)
def test_property_outcome_matches_documented_rule(
    reference: Decimal, observed: Decimal, direction: SignalDirection
) -> None:
    indication = _indication(direction, str(reference))
    future = (_bar(str(observed), offset_minutes=1),)
    result = verify_directional_indication(indication, future, horizon_bars=1)

    if direction is SignalDirection.BULLISH:
        expected = (
            VerificationOutcome.SUPPORTED
            if observed > reference
            else VerificationOutcome.NOT_SUPPORTED
        )
    else:
        expected = (
            VerificationOutcome.SUPPORTED
            if observed < reference
            else VerificationOutcome.NOT_SUPPORTED
        )
    assert result.outcome is expected


@given(
    closes=st.lists(
        st.decimals(min_value="10", max_value="10000", places=2, allow_nan=False),
        min_size=2,
        max_size=15,
    ),
    horizon_bars=st.integers(min_value=1, max_value=5),
)
def test_property_observations_beyond_horizon_do_not_affect_the_result(
    closes: list[Decimal], horizon_bars: int
) -> None:
    indication = _indication(SignalDirection.BULLISH, "100")
    full_future = tuple(_bar(str(c), offset_minutes=i + 1) for i, c in enumerate(closes))
    result_full = verify_directional_indication(indication, full_future, horizon_bars=horizon_bars)

    # Truncating the series to exactly `horizon_bars` (when enough exist)
    # must produce an identical result - anything beyond that point is
    # provably irrelevant to this single-point verification rule.
    if len(full_future) >= horizon_bars:
        truncated = full_future[:horizon_bars]
        result_truncated = verify_directional_indication(
            indication, truncated, horizon_bars=horizon_bars
        )
        assert result_full == result_truncated
