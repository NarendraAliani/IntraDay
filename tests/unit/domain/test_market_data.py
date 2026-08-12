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
from intraday.domain.market_data.contracts import Bar, Quote
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


def test_bar_rejects_negative_volume() -> None:
    with pytest.raises(ValueError):
        _bar(volume=Decimal("-1"))


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
