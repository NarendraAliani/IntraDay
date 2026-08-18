# tests/unit/application/services/test_instrument_master.py
#
# Follow-up to Checkpoint 63.x: pure unit tests for InstrumentMasterService
# with a fake provider - never a real network call.
from __future__ import annotations

from intraday.application.services.instrument_master import (
    InstrumentMasterEntry,
    InstrumentMasterService,
)
from intraday.domain.shared_kernel.contracts import Exchange


class _FakeProvider:
    def __init__(self, entries_by_exchange: dict[str, tuple[InstrumentMasterEntry, ...]]) -> None:
        self._entries_by_exchange = entries_by_exchange

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries_by_exchange.get(exchange.value, ())


def test_list_instruments_combines_exchange_symbol_and_display_name() -> None:
    provider = _FakeProvider(
        {
            "NSE": (
                InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance Industries"),
                InstrumentMasterEntry(symbol="TCS", display_name="Tata Consultancy Services"),
            )
        }
    )
    service = InstrumentMasterService(provider=provider)

    result = service.list_instruments(Exchange.NSE)

    assert result[0].instrument_id == "NSE:RELIANCE"
    assert result[0].display_name == "Reliance Industries"
    assert result[1].instrument_id == "NSE:TCS"
    assert result[1].display_name == "Tata Consultancy Services"


def test_list_instruments_empty_for_unknown_exchange_data() -> None:
    provider = _FakeProvider({})
    service = InstrumentMasterService(provider=provider)

    assert service.list_instruments(Exchange.BSE) == ()
