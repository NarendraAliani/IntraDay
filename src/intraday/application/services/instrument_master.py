# File: src/intraday/application/services/instrument_master.py
#
# Follow-up to Checkpoint 63.x: answers "what are ALL the tradable
# instruments for exchange X?" - the real data source the instrument
# picker's "Select All" needs to mean "all stocks on this exchange,"
# not just the handful the live-quote pipeline happens to have observed
# so far. Deliberately separate from `HistoricalDataCoverageService`/
# the DB-first bar pipeline - this answers a different question ("what
# instruments EXIST") than "what bars are cached."
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


class InstrumentMasterProvider(Protocol):
    def list_symbols(self, exchange: Exchange) -> tuple[str, ...]:
        """Every tradable cash-equity trading symbol on `exchange`,
        sorted, deduplicated - bare symbols (e.g. `"RELIANCE"`), not
        `InstrumentId`-formatted strings; the caller combines this with
        `exchange` itself."""
        ...


@dataclass(frozen=True, slots=True)
class InstrumentMasterService:
    provider: InstrumentMasterProvider

    def list_instrument_ids(self, exchange: Exchange) -> tuple[str, ...]:
        return tuple(
            str(make_instrument_id(exchange, symbol))
            for symbol in self.provider.list_symbols(exchange)
        )
