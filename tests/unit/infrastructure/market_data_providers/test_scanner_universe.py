# tests/unit/infrastructure/market_data_providers/test_scanner_universe.py
#
# Checkpoint 64.5 §22: isolated unit coverage for
# `resolve_scanner_universe()` - previously exercised only indirectly
# through the worker command's own tests. Covers every `universe_mode`,
# an unresolvable symbol (skipped, never guessed), a duplicate symbol
# (must not produce a duplicate subscription id - a real bug fixed in
# this checkpoint), an empty selection, and an invalid/missing
# watchlist.
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan import (
    scanner_universe as scanner_universe_module,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    InstrumentMasterEntry,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
from intraday.infrastructure.market_data_providers.dhan.scanner_universe import (
    resolve_scanner_universe,
)


def _config(**overrides: object) -> ScannerConfigurationRecord:
    base = ScannerConfigurationRecord(
        provider="dhan",
        enabled=True,
        timeframe="1m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=(),
        selected_watchlist_name="",
        selected_strategy_ids=(),
        configuration_version=1,
        requested_by="operator",
        requested_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


class _FakeWatchlistRepository:
    def __init__(self, stored: dict[tuple[str, str], list[str]]) -> None:
        self._stored = stored

    def save(
        self, name: str, owner: str, instrument_ids: list[str], *, created_at: datetime
    ) -> None:
        raise NotImplementedError

    def get(self, name: str, owner: str) -> list[str] | None:
        return self._stored.get((name, owner))

    def list_for_owner(self, owner: str) -> tuple[str, ...]:
        raise NotImplementedError

    def delete(self, name: str, owner: str) -> None:
        raise NotImplementedError


class _FakeInstrumentMaster:
    def __init__(self, entries_by_exchange: dict[str, tuple[InstrumentMasterEntry, ...]]) -> None:
        self._entries_by_exchange = entries_by_exchange

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries_by_exchange.get(exchange.value, ())


def _entry(symbol: str, security_id: int | None) -> InstrumentMasterEntry:
    return InstrumentMasterEntry(symbol=symbol, display_name=symbol, security_id=security_id)


def test_all_configured_mode_delegates_to_observation_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = (DhanInstrument(symbol="SENTINEL", security_id=1),)
    monkeypatch.setattr(scanner_universe_module, "observation_universe", lambda: sentinel)

    result = resolve_scanner_universe(
        _config(universe_mode="ALL_CONFIGURED"), watchlist_repository=_FakeWatchlistRepository({})
    )

    assert result == sentinel


def test_selected_mode_resolves_real_symbols_via_the_scrip_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_master = _FakeInstrumentMaster({"NSE": (_entry("RELIANCE", 2885), _entry("TCS", 11536))})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    config = _config(universe_mode="SELECTED", selected_instrument_ids=("NSE:RELIANCE", "NSE:TCS"))
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert {i.symbol for i in result} == {"RELIANCE", "TCS"}
    assert {i.security_id for i in result} == {2885, 11536}


def test_selected_mode_skips_an_unresolvable_symbol_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_master = _FakeInstrumentMaster({"NSE": (_entry("RELIANCE", 2885),)})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    config = _config(
        universe_mode="SELECTED", selected_instrument_ids=("NSE:RELIANCE", "NSE:NOT_A_REAL_SYMBOL")
    )
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert len(result) == 1
    assert result[0].symbol == "RELIANCE"


def test_selected_mode_skips_a_malformed_instrument_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_master = _FakeInstrumentMaster({"NSE": (_entry("RELIANCE", 2885),)})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    config = _config(
        universe_mode="SELECTED", selected_instrument_ids=("not-a-valid-instrument-id",)
    )
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert result == ()


def test_selected_mode_deduplicates_a_repeated_symbol_into_one_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_master = _FakeInstrumentMaster({"NSE": (_entry("RELIANCE", 2885),)})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    config = _config(
        universe_mode="SELECTED", selected_instrument_ids=("NSE:RELIANCE", "NSE:RELIANCE")
    )
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert len(result) == 1
    security_ids = [i.security_id for i in result]
    assert len(security_ids) == len(set(security_ids))


def test_selected_mode_with_an_empty_selection_resolves_to_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_master = _FakeInstrumentMaster({})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    config = _config(universe_mode="SELECTED", selected_instrument_ids=())
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert result == ()


def test_watchlist_mode_resolves_the_named_watchlists_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_master = _FakeInstrumentMaster({"NSE": (_entry("INFY", 1594),)})
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)
    repository = _FakeWatchlistRepository({("my-list", "operator"): ["NSE:INFY"]})

    config = _config(universe_mode="WATCHLIST", selected_watchlist_name="my-list")
    result = resolve_scanner_universe(config, watchlist_repository=repository)

    assert len(result) == 1
    assert result[0].symbol == "INFY"


def test_watchlist_mode_with_an_invalid_or_missing_watchlist_resolves_to_nothing() -> None:
    config = _config(universe_mode="WATCHLIST", selected_watchlist_name="does-not-exist")
    result = resolve_scanner_universe(config, watchlist_repository=_FakeWatchlistRepository({}))

    assert result == ()
