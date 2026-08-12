# tests/unit/domain/test_signal.py
#
# Unit tests for the Signal contract (Checkpoint 5), including the
# Signal/Order/Position/Trade separation invariant.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Side, Timeframe, Version
from intraday.domain.signal.contracts import Signal, SignalStatus

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _signal(**overrides: object) -> Signal:
    fields: dict[str, object] = {
        "signal_id": "sig-1",
        "strategy_id": "orb-v1",
        "strategy_version": Version(value="v1"),
        "instrument_id": RELIANCE,
        "generated_at": NOW,
        "timeframe": Timeframe.FIVE_MINUTE,
        "direction": Side.BUY,
        "theoretical_entry": Decimal("100"),
        "theoretical_stop_loss": Decimal("98"),
        "theoretical_targets": (Decimal("104"),),
        "feature_snapshot_version": Version(value="fv1"),
    }
    fields.update(overrides)
    return Signal(**fields)  # type: ignore[arg-type]


def test_valid_buy_signal_constructs() -> None:
    signal = _signal()
    assert signal.status is SignalStatus.PENDING


def test_buy_signal_requires_stop_below_entry() -> None:
    with pytest.raises(ValueError):
        _signal(theoretical_stop_loss=Decimal("101"))


def test_sell_signal_requires_stop_above_entry() -> None:
    with pytest.raises(ValueError):
        _signal(direction=Side.SELL, theoretical_stop_loss=Decimal("99"))


def test_confidence_must_be_within_zero_and_one() -> None:
    with pytest.raises(ValueError):
        _signal(confidence=Decimal("1.5"))


def test_expiry_must_be_after_generated_at() -> None:
    with pytest.raises(ValueError):
        _signal(expires_at=NOW)


def test_signal_has_no_order_or_position_fields() -> None:
    """Structural check for the Checkpoint 2 §5 separation: Signal must
    never carry order-status or position-exposure fields."""
    field_names = set(Signal.__dataclass_fields__)
    assert field_names.isdisjoint({"order_id", "position_id", "broker_order_id", "fill_price"})
