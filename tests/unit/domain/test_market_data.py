# tests/unit/domain/test_market_data.py
#
# Unit tests for the Bar and Quote market-data contracts (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar, PriceAdjustment, Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _bar(**overrides: object) -> Bar:
    fields: dict[str, object] = {
        "instrument_id": RELIANCE,
        "timeframe": Timeframe.FIVE_MINUTE,
        "timestamp": NOW,
        "open": Decimal("100"),
        "high": Decimal("105"),
        "low": Decimal("99"),
        "close": Decimal("102"),
        "volume": Decimal("1000"),
    }
    fields.update(overrides)
    return Bar(**fields)  # type: ignore[arg-type]


def test_valid_bar_constructs() -> None:
    bar = _bar()
    assert bar.close == Decimal("102")


def test_bar_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        _bar(timestamp=datetime(2026, 1, 1, 9, 20))


def test_bar_rejects_close_outside_high_low_range() -> None:
    with pytest.raises(ValueError):
        _bar(close=Decimal("110"))


def test_bar_rejects_high_below_max_of_open_and_close() -> None:
    """Checkpoint 14 §16 invariant: high >= max(open, close)."""
    with pytest.raises(ValueError):
        _bar(open=Decimal("100"), close=Decimal("103"), high=Decimal("102"), low=Decimal("99"))


def test_bar_rejects_low_above_min_of_open_and_close() -> None:
    """Checkpoint 14 §16 invariant: low <= min(open, close)."""
    with pytest.raises(ValueError):
        _bar(open=Decimal("100"), close=Decimal("97"), high=Decimal("105"), low=Decimal("98"))


def test_bar_rejects_negative_volume() -> None:
    with pytest.raises(ValueError):
        _bar(volume=Decimal("-1"))


def test_bar_accepts_zero_volume() -> None:
    """Zero volume is valid (an illiquid bar with no trades still has a
    well-defined OHLC from the last known price) - only negative volume
    is rejected."""
    bar = _bar(volume=Decimal("0"))
    assert bar.volume == Decimal("0")


def test_bar_timestamp_is_documented_as_close_time() -> None:
    """Checkpoint 14 §6: `Bar.timestamp` is the bar's CLOSE time, not its
    open time - a 5-minute bar covering [09:15, 09:20) IST is stamped
    09:20 IST. This test pins that convention so a future change to it
    must be a deliberate, visible edit here, not a silent drift."""
    close_time = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)  # 09:20 IST
    bar = _bar(timestamp=close_time)
    assert bar.timestamp == close_time


def test_bar_defaults_to_raw_price_adjustment() -> None:
    """Checkpoint 14 §10: a bar is RAW unless explicitly marked otherwise
    - no adjustment is ever silently applied."""
    bar = _bar()
    assert bar.adjustment is PriceAdjustment.RAW


def test_bar_can_be_explicitly_marked_adjusted() -> None:
    bar = _bar(adjustment=PriceAdjustment.ADJUSTED)
    assert bar.adjustment is PriceAdjustment.ADJUSTED


@given(
    low=st.decimals(min_value="1", max_value="100", places=2, allow_nan=False),
    spread=st.decimals(min_value="0", max_value="50", places=2, allow_nan=False),
)
def test_bar_ohlc_invariant_holds_for_generated_ranges(low: Decimal, spread: Decimal) -> None:
    high = low + spread
    mid = low + spread / 2
    bar = _bar(open=mid, high=high, low=low, close=mid)
    assert bar.low <= bar.open <= bar.high
    assert bar.low <= bar.close <= bar.high


def test_quote_rejects_bid_above_ask() -> None:
    with pytest.raises(ValueError):
        Quote(
            instrument_id=RELIANCE,
            timestamp=NOW,
            last_price=Decimal("100"),
            bid=Decimal("101"),
            ask=Decimal("100"),
        )


def test_quote_requires_positive_last_price() -> None:
    with pytest.raises(ValueError):
        Quote(instrument_id=RELIANCE, timestamp=NOW, last_price=Decimal("0"))
