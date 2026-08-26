# tests/unit/domain/market_data/test_observation_identity.py
#
# Checkpoint 64.87 Part B: coverage for `classify_observation()`, the
# canonical instrument+source_timestamp+snapshot observation-identity
# rule that replaces "advancing fetched_at == new observation" (the
# confirmed 64.85 defect).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.market_data.quality import ObservationComparison, classify_observation
from intraday.domain.shared_kernel.contracts import Exchange

INFY = make_instrument_id(Exchange.NSE, "INFY")
TCS = make_instrument_id(Exchange.NSE, "TCS")
T1 = datetime(2026, 1, 5, 4, 44, 0, tzinfo=UTC)
T2 = datetime(2026, 1, 5, 4, 44, 1, tzinfo=UTC)


def _quote(
    instrument_id=INFY,
    timestamp: datetime = T1,
    price: str = "100.00",
    cumulative_volume: str | None = None,
) -> Quote:
    return Quote(
        instrument_id=instrument_id,
        timestamp=timestamp,
        last_price=Decimal(price),
        cumulative_volume=Decimal(cumulative_volume) if cumulative_volume is not None else None,
    )


def test_first_observation_ever_is_new() -> None:
    assert classify_observation(None, _quote()) is ObservationComparison.NEW


def test_same_source_timestamp_identical_snapshot_is_stale_duplicate() -> None:
    previous = _quote(timestamp=T1, price="100.00")
    candidate = _quote(timestamp=T1, price="100.00")
    assert classify_observation(previous, candidate) is ObservationComparison.STALE_DUPLICATE


def test_different_source_timestamp_same_price_is_new() -> None:
    # Three legitimate same-price ticks at three different timestamps
    # must ALL survive - price equality alone is never the dedup key.
    previous = _quote(timestamp=T1, price="100.00")
    candidate = _quote(timestamp=T2, price="100.00")
    assert classify_observation(previous, candidate) is ObservationComparison.NEW


def test_different_source_timestamp_different_price_is_new() -> None:
    previous = _quote(timestamp=T1, price="100.00")
    candidate = _quote(timestamp=T2, price="101.00")
    assert classify_observation(previous, candidate) is ObservationComparison.NEW


def test_same_source_timestamp_different_price_is_conflicting_not_discarded() -> None:
    previous = _quote(timestamp=T1, price="100.00")
    candidate = _quote(timestamp=T1, price="101.00")
    result = classify_observation(previous, candidate)
    assert result is ObservationComparison.CONFLICTING_SAME_TIMESTAMP
    assert result is not ObservationComparison.STALE_DUPLICATE


def test_same_source_timestamp_different_cumulative_volume_is_conflicting() -> None:
    previous = _quote(timestamp=T1, price="100.00", cumulative_volume="1000")
    candidate = _quote(timestamp=T1, price="100.00", cumulative_volume="1500")
    result = classify_observation(previous, candidate)
    assert result is ObservationComparison.CONFLICTING_SAME_TIMESTAMP


def test_same_source_timestamp_same_price_and_cumulative_volume_is_stale() -> None:
    previous = _quote(timestamp=T1, price="100.00", cumulative_volume="1000")
    candidate = _quote(timestamp=T1, price="100.00", cumulative_volume="1000")
    assert classify_observation(previous, candidate) is ObservationComparison.STALE_DUPLICATE


def test_mismatched_instrument_ids_raises() -> None:
    previous = _quote(instrument_id=INFY, timestamp=T1)
    candidate = _quote(instrument_id=TCS, timestamp=T1)
    with pytest.raises(ValueError):
        classify_observation(previous, candidate)


def test_three_legitimate_same_price_ticks_all_classified_new_in_sequence() -> None:
    t3 = datetime(2026, 1, 5, 4, 44, 2, tzinfo=UTC)
    q1 = _quote(timestamp=T1, price="100.00")
    q2 = _quote(timestamp=T2, price="100.00")
    q3 = _quote(timestamp=t3, price="100.00")

    assert classify_observation(None, q1) is ObservationComparison.NEW
    assert classify_observation(q1, q2) is ObservationComparison.NEW
    assert classify_observation(q2, q3) is ObservationComparison.NEW
