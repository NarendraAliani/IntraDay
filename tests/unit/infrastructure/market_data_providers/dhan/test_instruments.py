# tests/unit/infrastructure/market_data_providers/dhan/test_instruments.py
#
# Checkpoint 23: coverage for the configuration-driven observation
# universe (Checkpoint 23 §7).
from __future__ import annotations

import pytest

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instruments import (
    UnknownObservationSymbolError,
    observation_universe,
)


class _FakeInstrumentMaster:
    """Never touches the network - the Checkpoint 64 test double for the
    real scrip-master fallback `observation_universe()` now has."""

    def __init__(self, entries: tuple[InstrumentMasterEntry, ...] = ()) -> None:
        self._entries = entries

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries


def test_default_universe_is_the_four_documented_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_DATA_OBSERVATION_SYMBOLS", raising=False)

    universe = observation_universe()

    symbols = {instrument.symbol for instrument in universe}
    assert symbols == {"RELIANCE", "TCS", "INFY", "HDFCBANK"}


def test_universe_is_configuration_driven_not_hard_coded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_OBSERVATION_SYMBOLS", "TCS,INFY")

    universe = observation_universe()

    symbols = {instrument.symbol for instrument in universe}
    assert symbols == {"TCS", "INFY"}


def test_unverified_symbol_raises_rather_than_guessing_a_security_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_DATA_OBSERVATION_SYMBOLS", "NOTAREALSYMBOL")

    # A fake, empty scrip master - proves the raise happens because the
    # symbol genuinely isn't found ANYWHERE, not because of a real
    # network call this unit test must never make.
    with pytest.raises(UnknownObservationSymbolError):
        observation_universe(instrument_master=_FakeInstrumentMaster())


def test_a_symbol_outside_the_four_hardcoded_entries_resolves_via_the_scrip_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 64: the real fix for NewStatus.md's named gap - the
    live-quote observation universe is no longer architecturally capped
    at four hand-verified symbols. `WIPRO` is deliberately NOT in
    `_KNOWN_INSTRUMENTS` - this proves it resolves anyway, via the
    (here, faked) real scrip master."""
    monkeypatch.setenv("MARKET_DATA_OBSERVATION_SYMBOLS", "WIPRO")
    fake_master = _FakeInstrumentMaster(
        (InstrumentMasterEntry(symbol="WIPRO", display_name="Wipro Limited", security_id=3787),)
    )

    universe = observation_universe(instrument_master=fake_master)

    assert len(universe) == 1
    assert universe[0].symbol == "WIPRO"
    assert universe[0].security_id == 3787
    assert universe[0].exchange_segment == "NSE_EQ"


def test_a_scrip_master_entry_missing_a_security_id_is_not_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_DATA_OBSERVATION_SYMBOLS", "WIPRO")
    fake_master = _FakeInstrumentMaster(
        (InstrumentMasterEntry(symbol="WIPRO", display_name="Wipro Limited", security_id=None),)
    )

    with pytest.raises(UnknownObservationSymbolError):
        observation_universe(instrument_master=fake_master)


def test_known_instruments_never_call_the_injected_master_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default four symbols must stay a zero-network fast path -
    proven by a fake master that raises if ever called."""

    class _RaisesIfCalled:
        def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
            raise AssertionError("the scrip-master fallback must not run for a known instrument")

    monkeypatch.delenv("MARKET_DATA_OBSERVATION_SYMBOLS", raising=False)

    universe = observation_universe(instrument_master=_RaisesIfCalled())

    assert len(universe) == 4


def test_every_instrument_uses_the_nse_eq_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_DATA_OBSERVATION_SYMBOLS", raising=False)

    universe = observation_universe()

    assert all(instrument.exchange_segment == "NSE_EQ" for instrument in universe)


def test_security_ids_are_distinct_positive_integers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_DATA_OBSERVATION_SYMBOLS", raising=False)

    universe = observation_universe()

    security_ids = [instrument.security_id for instrument in universe]
    assert len(security_ids) == len(set(security_ids))
    assert all(security_id > 0 for security_id in security_ids)
