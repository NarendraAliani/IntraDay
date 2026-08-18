# File: src/intraday/application/services/instrument_master.py
#
# Follow-up to Checkpoint 63.x: answers "what are ALL the tradable
# instruments for exchange X, and what are they actually called?" - the
# real data source the instrument picker's "Select All" needs to mean
# "all stocks on this exchange," and the real display-name source so
# the picker can show "Reliance Industries" rather than a bare
# "NSE:RELIANCE" instrument id.
#
# Provider-neutral by the same Protocol pattern every other repository
# in this codebase uses - `DhanInstrumentMasterProvider`
# (infrastructure/market_data_providers/dhan/instrument_master.py) is
# the one real implementation today.
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange


@dataclass(frozen=True, slots=True)
class InstrumentMasterEntry:
    symbol: str
    display_name: str
    # Broker-native numeric identifier (Dhan's `security_id`) - `None`
    # for any source/test fixture that doesn't carry one. Needed to call
    # a broker's historical-candle REST API, which addresses instruments
    # by this ID, never by symbol (see `dhan/historical_client.py`).
    security_id: int | None = None


class InstrumentMasterProvider(Protocol):
    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        """Every genuine, tradable cash-equity instrument on
        `exchange`, sorted by symbol, deduplicated - with its real
        display name, never a fabricated or guessed one."""
        ...


@dataclass(frozen=True, slots=True)
class InstrumentSummary:
    instrument_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class InstrumentMasterService:
    provider: InstrumentMasterProvider

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentSummary, ...]:
        return tuple(
            InstrumentSummary(
                instrument_id=str(make_instrument_id(exchange, entry.symbol)),
                display_name=entry.display_name,
            )
            for entry in self.provider.list_instruments(exchange)
        )
