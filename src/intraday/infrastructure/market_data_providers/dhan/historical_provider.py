# File: src/intraday/infrastructure/market_data_providers/dhan/historical_provider.py
#
# The real Dhan adapter `synthetic_historical.py` predicted: "Swapping
# this for a real Dhan adapter later is a single-class substitution -
# nothing above this Protocol boundary... needs to change." Satisfies
# `HistoricalDataPreparationService`'s `HistoricalBarProvider` Protocol
# using the genuine `historical_client.py` REST client instead of
# generated fixture data.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.application.services.instrument_master import InstrumentMasterProvider
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
    DhanHistoricalDataError,
    fetch_daily_candles,
    fetch_intraday_candles,
)

# Dhan's own documented exchange-segment vocabulary for cash equities -
# see `instruments.py`'s NSE_EQ_SEGMENT for the NSE precedent; BSE_EQ is
# the equivalent, symmetrically-named segment for BSE.
_EXCHANGE_SEGMENTS: dict[Exchange, str] = {Exchange.NSE: "NSE_EQ", Exchange.BSE: "BSE_EQ"}

# Dhan's intraday endpoint only supports these five interval values
# (see `historical_client.py`'s module docstring) - this project's
# Timeframe enum has two members (3m, 30m) with no matching Dhan
# interval. Those are an honest, named gap, not silently rounded to a
# neighboring interval.
_INTRADAY_INTERVAL_MINUTES: dict[Timeframe, int] = {
    Timeframe.ONE_MINUTE: 1,
    Timeframe.FIVE_MINUTE: 5,
    Timeframe.FIFTEEN_MINUTE: 15,
    Timeframe.ONE_HOUR: 60,
}


class DhanHistoricalBarProviderUnavailableError(RuntimeError):
    """Raised whenever this provider cannot serve a `fetch()` request -
    no credentials configured, an unsupported timeframe, an instrument
    absent from the scrip master, or any Dhan API failure. The ONE
    exception type `HistoricalDataPreparationService` needs to catch
    (mirrors `synthetic_historical.py`'s own
    `HistoricalBarProviderUnavailableError` contract exactly, so this
    real adapter is a genuine drop-in substitute for that stand-in)."""


def _candle_to_bar(
    instrument_id: InstrumentId, timeframe: Timeframe, candle: DhanHistoricalCandle
) -> Bar:
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=candle.timestamp,
        open=Decimal(str(candle.open)),
        high=Decimal(str(candle.high)),
        low=Decimal(str(candle.low)),
        close=Decimal(str(candle.close)),
        volume=Decimal(str(candle.volume)),
    )


@dataclass
class DhanHistoricalBarProvider:
    """Satisfies `HistoricalDataPreparationService`'s `HistoricalBarProvider`
    Protocol using real Dhan REST calls. `client_id`/`access_token` are
    resolved by the caller (typically via `DhanSettingsService.
    effective_credentials()`, this codebase's one canonical credential
    source - see `market_data_ingestion_runtime.py`) and passed in
    explicitly, so this class has no direct Django/settings dependency
    of its own, matching every other provider in this package."""

    client_id: str
    access_token: str
    instrument_master: InstrumentMasterProvider

    def _security_id(self, exchange: Exchange, symbol: str) -> int:
        for entry in self.instrument_master.list_instruments(exchange):
            if entry.symbol == symbol and entry.security_id is not None:
                return entry.security_id
        raise DhanHistoricalBarProviderUnavailableError(
            f"no verified Dhan security_id for {exchange.value}:{symbol} - "
            "not present in the current scrip master."
        )

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        exchange, symbol = parse_instrument_id(instrument_id)
        exchange_segment = _EXCHANGE_SEGMENTS.get(exchange)
        if exchange_segment is None:
            raise DhanHistoricalBarProviderUnavailableError(
                f"Dhan historical data is not supported for exchange {exchange.value!r}."
            )
        security_id = self._security_id(exchange, symbol)

        try:
            if timeframe is Timeframe.DAY:
                candles = fetch_daily_candles(
                    client_id=self.client_id,
                    access_token=self.access_token,
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    from_date=start.date(),
                    to_date=end.date(),
                )
            else:
                interval_minutes = _INTRADAY_INTERVAL_MINUTES.get(timeframe)
                if interval_minutes is None:
                    raise DhanHistoricalBarProviderUnavailableError(
                        f"Dhan's intraday historical API has no {timeframe.value!r} interval - "
                        "only 1m/5m/15m/1h and daily bars are supported."
                    )
                candles = fetch_intraday_candles(
                    client_id=self.client_id,
                    access_token=self.access_token,
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    interval_minutes=interval_minutes,
                    from_time=start,
                    to_time=end,
                )
        except DhanHistoricalDataError as exc:
            raise DhanHistoricalBarProviderUnavailableError(
                f"Dhan historical fetch failed for {instrument_id} {timeframe.value}: {exc}"
            ) from exc

        return tuple(
            _candle_to_bar(instrument_id, timeframe, candle)
            for candle in candles
            if start <= candle.timestamp <= end
        )


__all__ = ["DhanHistoricalBarProvider", "DhanHistoricalBarProviderUnavailableError"]
