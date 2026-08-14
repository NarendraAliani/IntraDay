# tests/unit/infrastructure/market_data_providers/dhan/test_instruments.py
#
# Checkpoint 23: coverage for the configuration-driven observation
# universe (Checkpoint 23 §7).
from __future__ import annotations

import pytest

from intraday.infrastructure.market_data_providers.dhan.instruments import (
    UnknownObservationSymbolError,
    observation_universe,
)


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

    with pytest.raises(UnknownObservationSymbolError):
        observation_universe()


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
