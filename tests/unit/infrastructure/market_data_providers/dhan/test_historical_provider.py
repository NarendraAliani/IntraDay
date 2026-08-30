# tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py
#
# Unit coverage for `DhanHistoricalBarProvider` - the real adapter that
# satisfies `HistoricalDataPreparationService`'s `HistoricalBarProvider`
# Protocol. Never makes a real network call - `historical_client`'s own
# `fetch_daily_candles`/`fetch_intraday_candles` are monkeypatched at
# the module the provider actually calls them from.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan import historical_provider
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
)
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    DhanHistoricalBarProvider,
    DhanHistoricalBarProviderUnavailableError,
)

RELIANCE_ID = make_instrument_id(Exchange.NSE, "RELIANCE")


class _FakeInstrumentMaster:
    def __init__(self, entries: tuple[InstrumentMasterEntry, ...]) -> None:
        self._entries = entries

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries


def _provider(entries: tuple[InstrumentMasterEntry, ...]) -> DhanHistoricalBarProvider:
    return DhanHistoricalBarProvider(
        client_id="fake-client-id",
        access_token="fake-token",
        instrument_master=_FakeInstrumentMaster(entries),
    )


def test_fetch_resolves_security_id_and_delegates_to_the_daily_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_fetch_daily_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return (
            DhanHistoricalCandle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000,
            ),
        )

    monkeypatch.setattr(historical_provider, "fetch_daily_candles", _fake_fetch_daily_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    bars = provider.fetch(
        RELIANCE_ID,
        Timeframe.DAY,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
    )

    assert len(bars) == 1
    assert bars[0].instrument_id == RELIANCE_ID
    assert calls[0]["security_id"] == 2885
    assert calls[0]["exchange_segment"] == "NSE_EQ"


def test_fetch_delegates_to_the_intraday_client_for_a_minute_timeframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return ()

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    provider.fetch(
        RELIANCE_ID,
        Timeframe.FIVE_MINUTE,
        datetime(2024, 1, 1, 9, 15, tzinfo=UTC),
        datetime(2024, 1, 1, 15, 30, tzinfo=UTC),
    )

    assert calls[0]["interval_minutes"] == 5


def test_unknown_security_id_raises_unavailable_never_guesses() -> None:
    provider = _provider(())  # scrip master has no entry for RELIANCE at all
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.DAY,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_unsupported_intraday_timeframe_raises_unavailable_never_silently_rounds() -> None:
    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.THREE_MINUTE,  # Dhan has no 3-minute interval
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_a_dhan_client_error_is_wrapped_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from intraday.infrastructure.market_data_providers.dhan.historical_client import (
        DhanHistoricalConnectionError,
    )

    def _raise(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        raise DhanHistoricalConnectionError("boom")

    monkeypatch.setattr(historical_provider, "fetch_daily_candles", _raise)

    provider = _provider(
        (InstrumentMasterEntry(symbol="RELIANCE", display_name="Reliance", security_id=2885),)
    )
    with pytest.raises(DhanHistoricalBarProviderUnavailableError):
        provider.fetch(
            RELIANCE_ID,
            Timeframe.DAY,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_provenance_is_real_dhan() -> None:
    """Checkpoint 65.23: `HistoricalDataPreparationService` reads this
    attribute (`getattr(self.provider, "provenance", PROVENANCE_UNKNOWN)`)
    to stamp `HistoricalBar.provenance` - a real Dhan fetch must never
    silently fall back to UNKNOWN just because this provider declared
    nothing, which is exactly the defect 65.22-R found and this fixes."""
    from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN

    provider = _provider(())
    assert provider.provenance == PROVENANCE_REAL_DHAN
