# tests/unit/signal_intelligence/signal_lifecycle/test_lifecycle.py
#
# Unit tests for the Checkpoint 20 signal-lifecycle rule - pure Python,
# no database, no Django, runs unconditionally.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.signal_lifecycle.contracts import (
    LIFECYCLE_DEFINITION_NAME,
    LIFECYCLE_DEFINITION_VERSION,
    SignalLifecycle,
    SignalLifecycleState,
)
from intraday.signal_intelligence.signal_lifecycle.errors import (
    InvalidExpiryError,
    NonMonotonicTimeError,
)
from intraday.signal_intelligence.signal_lifecycle.lifecycle import (
    advance_lifecycle,
    advance_lifecycles,
    compute_expiry_from_bars,
    create_lifecycle,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
SIGNAL_TIME = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
FEATURE_VERSION = Version(value="v1")


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
    *, timestamp: datetime = SIGNAL_TIME, timeframe: Timeframe = Timeframe.FIVE_MINUTE
) -> DirectionalIndication:
    return DirectionalIndication(
        definition_name="sma_ema_atr_directional",
        definition_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=timeframe,
        timestamp=timestamp,
        direction=SignalDirection.BULLISH,
        price=Decimal("100"),
        sma=_feature("sma_20", "95"),
        ema=_feature("ema_10", "98"),
        atr=_feature("atr_14", "5"),
    )


EXPIRES_AT = SIGNAL_TIME + timedelta(minutes=15)


# ---------------------------------------------------------------------------
# State creation
# ---------------------------------------------------------------------------


def test_create_lifecycle_begins_active_when_as_of_before_expiry() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    assert lifecycle.state is SignalLifecycleState.ACTIVE


def test_create_lifecycle_identity_and_timestamps() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    assert lifecycle.lifecycle_definition_name == LIFECYCLE_DEFINITION_NAME
    assert lifecycle.lifecycle_definition_version == LIFECYCLE_DEFINITION_VERSION
    assert lifecycle.instrument_id == RELIANCE
    assert lifecycle.timeframe == Timeframe.FIVE_MINUTE
    assert lifecycle.signal_timestamp == SIGNAL_TIME
    assert lifecycle.expires_at == EXPIRES_AT
    assert lifecycle.as_of == SIGNAL_TIME
    assert lifecycle.indication == indication


def test_create_lifecycle_for_an_already_expired_indication_is_legitimate() -> None:
    """Creating a lifecycle for historical/replayed data where `as_of`
    is already past `expires_at` is a legitimate, honest outcome (§4) -
    not an error."""
    indication = _indication()
    far_future = EXPIRES_AT + timedelta(hours=1)
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=far_future)
    assert lifecycle.state is SignalLifecycleState.EXPIRED


def test_expires_at_before_signal_timestamp_rejected() -> None:
    indication = _indication()
    with pytest.raises(InvalidExpiryError):
        create_lifecycle(indication, SIGNAL_TIME - timedelta(minutes=1), as_of=SIGNAL_TIME)


def test_expires_at_equal_to_signal_timestamp_rejected() -> None:
    indication = _indication()
    with pytest.raises(InvalidExpiryError):
        create_lifecycle(indication, SIGNAL_TIME, as_of=SIGNAL_TIME)


# ---------------------------------------------------------------------------
# Expiry boundary
# ---------------------------------------------------------------------------


def test_one_microsecond_before_expiry_is_active() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(
        indication, EXPIRES_AT, as_of=EXPIRES_AT - timedelta(microseconds=1)
    )
    assert lifecycle.state is SignalLifecycleState.ACTIVE


def test_exactly_at_expiry_is_expired() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=EXPIRES_AT)
    assert lifecycle.state is SignalLifecycleState.EXPIRED


def test_one_microsecond_after_expiry_is_expired() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(
        indication, EXPIRES_AT, as_of=EXPIRES_AT + timedelta(microseconds=1)
    )
    assert lifecycle.state is SignalLifecycleState.EXPIRED


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def test_advance_from_active_to_expired() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    advanced = advance_lifecycle(lifecycle, EXPIRES_AT)
    assert lifecycle.state is SignalLifecycleState.ACTIVE  # original untouched
    assert advanced.state is SignalLifecycleState.EXPIRED


def test_advance_active_to_active_stays_active() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    advanced = advance_lifecycle(lifecycle, SIGNAL_TIME + timedelta(minutes=5))
    assert advanced.state is SignalLifecycleState.ACTIVE


def test_advance_expired_to_expired_stays_expired() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=EXPIRES_AT)
    advanced = advance_lifecycle(lifecycle, EXPIRES_AT + timedelta(hours=1))
    assert advanced.state is SignalLifecycleState.EXPIRED


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


def test_advancing_to_an_earlier_as_of_is_rejected() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME + timedelta(minutes=5))
    with pytest.raises(NonMonotonicTimeError):
        advance_lifecycle(lifecycle, SIGNAL_TIME)  # earlier than lifecycle.as_of


def test_expired_cannot_be_rewound_back_to_active() -> None:
    """The concrete case the state model makes structurally impossible
    through forward time, and structurally rejected through backward
    time: EXPIRED -> ACTIVE never happens."""
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=EXPIRES_AT)
    assert lifecycle.state is SignalLifecycleState.EXPIRED
    with pytest.raises(NonMonotonicTimeError):
        advance_lifecycle(lifecycle, SIGNAL_TIME)  # attempt to rewind before expiry


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_advancing_to_the_same_as_of_is_idempotent() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    advanced = advance_lifecycle(lifecycle, SIGNAL_TIME)
    assert advanced == lifecycle


def test_repeated_advance_to_same_later_as_of_is_idempotent() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    once = advance_lifecycle(lifecycle, EXPIRES_AT)
    twice = advance_lifecycle(once, EXPIRES_AT)
    assert once == twice


# ---------------------------------------------------------------------------
# Timezone / time semantics
# ---------------------------------------------------------------------------


def test_naive_expires_at_rejected() -> None:
    indication = _indication()
    naive = datetime(2026, 1, 1, 4, 5)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        create_lifecycle(indication, naive, as_of=SIGNAL_TIME)


def test_naive_as_of_rejected() -> None:
    indication = _indication()
    naive = datetime(2026, 1, 1, 4, 5)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        create_lifecycle(indication, EXPIRES_AT, as_of=naive)


def test_non_utc_offset_rejected() -> None:
    from datetime import timezone

    indication = _indication()
    ist = datetime(2026, 1, 1, 9, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with pytest.raises(ValueError):
        create_lifecycle(indication, EXPIRES_AT, as_of=ist)


# ---------------------------------------------------------------------------
# compute_expiry_from_bars helper
# ---------------------------------------------------------------------------


def test_compute_expiry_from_bars_uses_timeframe_duration() -> None:
    indication = _indication(timeframe=Timeframe.FIVE_MINUTE)
    expiry = compute_expiry_from_bars(indication, lifetime_bars=3)
    assert expiry == SIGNAL_TIME + timedelta(minutes=15)


def test_compute_expiry_from_bars_rejects_non_positive_lifetime() -> None:
    indication = _indication()
    with pytest.raises(ValueError):
        compute_expiry_from_bars(indication, lifetime_bars=0)


def test_compute_expiry_from_bars_feeds_directly_into_create_lifecycle() -> None:
    indication = _indication(timeframe=Timeframe.ONE_MINUTE)
    expiry = compute_expiry_from_bars(indication, lifetime_bars=10)
    lifecycle = create_lifecycle(indication, expiry, as_of=SIGNAL_TIME)
    assert lifecycle.state is SignalLifecycleState.ACTIVE
    assert lifecycle.expires_at == SIGNAL_TIME + timedelta(minutes=10)


# ---------------------------------------------------------------------------
# Identity preservation
# ---------------------------------------------------------------------------


def test_instrument_and_timeframe_preserved_through_advance() -> None:
    indication = _indication(timeframe=Timeframe.ONE_MINUTE)
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    advanced = advance_lifecycle(lifecycle, EXPIRES_AT)
    assert advanced.instrument_id == RELIANCE
    assert advanced.timeframe == Timeframe.ONE_MINUTE
    assert advanced.signal_timestamp == SIGNAL_TIME


def test_lifecycle_construction_rejects_instrument_mismatch_with_indication() -> None:
    indication = _indication()
    with pytest.raises(ValueError, match="instrument_id"):
        SignalLifecycle(
            lifecycle_definition_name=LIFECYCLE_DEFINITION_NAME,
            lifecycle_definition_version=LIFECYCLE_DEFINITION_VERSION,
            instrument_id=TCS,  # mismatched on purpose
            timeframe=indication.timeframe,
            signal_timestamp=indication.timestamp,
            expires_at=EXPIRES_AT,
            as_of=SIGNAL_TIME,
            state=SignalLifecycleState.ACTIVE,
            indication=indication,
        )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_source_indication_unchanged_after_lifecycle_operations() -> None:
    indication = _indication()
    before = indication
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    advance_lifecycle(lifecycle, EXPIRES_AT)
    assert indication == before


def test_advance_never_mutates_the_original_lifecycle_object() -> None:
    indication = _indication()
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    original_as_of = lifecycle.as_of
    original_state = lifecycle.state
    advance_lifecycle(lifecycle, EXPIRES_AT)
    assert lifecycle.as_of == original_as_of
    assert lifecycle.state == original_state


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_identical_lifecycle() -> None:
    indication = _indication()
    first = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    second = create_lifecycle(indication, EXPIRES_AT, as_of=SIGNAL_TIME)
    assert first == second


# ---------------------------------------------------------------------------
# Multi-lifecycle collection operation
# ---------------------------------------------------------------------------


def test_advance_lifecycles_preserves_order_and_evaluates_independently() -> None:
    indication_a = _indication()
    indication_b = _indication(timestamp=SIGNAL_TIME + timedelta(minutes=1))
    lifecycle_a = create_lifecycle(
        indication_a, SIGNAL_TIME + timedelta(minutes=2), as_of=SIGNAL_TIME
    )
    lifecycle_b = create_lifecycle(
        indication_b, SIGNAL_TIME + timedelta(hours=1), as_of=SIGNAL_TIME + timedelta(minutes=1)
    )

    advanced = advance_lifecycles((lifecycle_a, lifecycle_b), SIGNAL_TIME + timedelta(minutes=3))

    assert advanced[0].indication == indication_a
    assert advanced[0].state is SignalLifecycleState.EXPIRED  # 2-min expiry, now at +3min
    assert advanced[1].indication == indication_b
    assert advanced[1].state is SignalLifecycleState.ACTIVE  # 1-hour expiry, still active


def test_advance_lifecycles_one_signals_expiry_does_not_affect_another() -> None:
    indication_a = _indication()
    indication_b = _indication(timestamp=SIGNAL_TIME)
    short_lived = create_lifecycle(
        indication_a, SIGNAL_TIME + timedelta(minutes=1), as_of=SIGNAL_TIME
    )
    long_lived = create_lifecycle(indication_b, SIGNAL_TIME + timedelta(hours=5), as_of=SIGNAL_TIME)
    as_of = SIGNAL_TIME + timedelta(minutes=2)  # short expired, long still active
    advanced = advance_lifecycles((short_lived, long_lived), as_of)
    assert advanced[0].state is SignalLifecycleState.EXPIRED
    assert advanced[1].state is SignalLifecycleState.ACTIVE


# ---------------------------------------------------------------------------
# Property-based testing
# ---------------------------------------------------------------------------


@given(offset_seconds=st.integers(min_value=-3600, max_value=3600))
def test_property_state_matches_boundary_rule(offset_seconds: int) -> None:
    indication = _indication()
    as_of = EXPIRES_AT + timedelta(seconds=offset_seconds)
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=as_of)
    expected = SignalLifecycleState.EXPIRED if as_of >= EXPIRES_AT else SignalLifecycleState.ACTIVE
    assert lifecycle.state is expected


@given(
    first_offset=st.integers(min_value=0, max_value=1800),
    second_offset=st.integers(min_value=0, max_value=1800),
)
def test_property_advancing_forward_never_rewinds_state_to_active(
    first_offset: int, second_offset: int
) -> None:
    """Once EXPIRED, any forward-moving as_of stays EXPIRED - the
    structural guarantee the state model provides without a transition
    table."""
    indication = _indication()
    first_as_of = EXPIRES_AT + timedelta(seconds=first_offset)
    lifecycle = create_lifecycle(indication, EXPIRES_AT, as_of=first_as_of)
    assert lifecycle.state is SignalLifecycleState.EXPIRED

    second_as_of = first_as_of + timedelta(seconds=second_offset)
    advanced = advance_lifecycle(lifecycle, second_as_of)
    assert advanced.state is SignalLifecycleState.EXPIRED
