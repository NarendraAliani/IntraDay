# tests/unit/domain/test_instrument.py
#
# Unit tests for the Instrument contract (Checkpoint 5), including the
# F&O-exclusion invariant validation required by Checkpoint 5 Section 21.
from __future__ import annotations

from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import (
    Instrument,
    InstrumentType,
    TradingStatus,
    make_instrument_id,
)
from intraday.domain.shared_kernel.contracts import Exchange


def _make(
    instrument_type: InstrumentType = InstrumentType.EQUITY,
    trading_status: TradingStatus = TradingStatus.ACTIVE,
) -> Instrument:
    return Instrument(
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        instrument_type=instrument_type,
        trading_status=trading_status,
        price_tick_size=Decimal("0.05"),
        lot_size=1,
    )


def test_make_instrument_id_is_deterministic() -> None:
    a = make_instrument_id(Exchange.NSE, "reliance")
    b = make_instrument_id(Exchange.NSE, "RELIANCE")
    assert a == b == "NSE:RELIANCE"


def test_active_equity_is_tradable() -> None:
    assert _make().is_tradable is True


def test_suspended_equity_is_not_tradable() -> None:
    assert _make(trading_status=TradingStatus.SUSPENDED).is_tradable is False


def test_index_is_never_tradable_even_if_active() -> None:
    """NIFTY/SENSEX-style reference instruments must never be tradable,
    regardless of status — Rule 2's intraday-cash-equity-only scope
    enforced structurally."""
    assert _make(instrument_type=InstrumentType.INDEX).is_tradable is False


def test_instrument_type_enum_has_no_derivative_members() -> None:
    """Explicit F&O-exclusion validation (Checkpoint 5 Section 21): the
    enum must contain only EQUITY and INDEX — never FUTURE, OPTION, or any
    other derivative concept."""
    member_names = {member.name for member in InstrumentType}
    assert member_names == {"EQUITY", "INDEX"}
    forbidden = {"FUTURE", "OPTION", "FUTURES", "OPTIONS", "OPTION_CHAIN", "STRIKE", "EXPIRY"}
    assert member_names.isdisjoint(forbidden)


def test_instrument_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError):
        Instrument(
            instrument_id=make_instrument_id(Exchange.NSE, "X"),
            symbol="   ",
            exchange=Exchange.NSE,
            instrument_type=InstrumentType.EQUITY,
            trading_status=TradingStatus.ACTIVE,
            price_tick_size=Decimal("0.05"),
        )


def test_instrument_rejects_float_tick_size() -> None:
    with pytest.raises(TypeError):
        Instrument(
            instrument_id=make_instrument_id(Exchange.NSE, "X"),
            symbol="X",
            exchange=Exchange.NSE,
            instrument_type=InstrumentType.EQUITY,
            trading_status=TradingStatus.ACTIVE,
            price_tick_size=0.05,  # type: ignore[arg-type]
        )
