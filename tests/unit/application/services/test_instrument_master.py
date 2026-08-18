# tests/unit/application/services/test_instrument_master.py
#
# Follow-up to Checkpoint 63.x: pure unit tests for InstrumentMasterService
# with a fake provider - never a real network call.
from __future__ import annotations

from intraday.application.services.instrument_master import InstrumentMasterService
from intraday.domain.shared_kernel.contracts import Exchange


class _FakeProvider:
    def __init__(self, symbols_by_exchange: dict[str, tuple[str, ...]]) -> None:
        self._symbols_by_exchange = symbols_by_exchange

    def list_symbols(self, exchange: Exchange) -> tuple[str, ...]:
        return self._symbols_by_exchange.get(exchange.value, ())


def test_list_instrument_ids_combines_exchange_and_symbol() -> None:
    provider = _FakeProvider({"NSE": ("RELIANCE", "TCS")})
    service = InstrumentMasterService(provider=provider)

    result = service.list_instrument_ids(Exchange.NSE)

    assert result == ("NSE:RELIANCE", "NSE:TCS")


def test_list_instrument_ids_empty_for_unknown_exchange_data() -> None:
    provider = _FakeProvider({})
    service = InstrumentMasterService(provider=provider)

    assert service.list_instrument_ids(Exchange.BSE) == ()
