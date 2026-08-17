# File: src/intraday/application/repositories/historical_bars.py
#
# Checkpoint 63.x: repository Protocols for the DB-first historical-bar
# archive. Split into a READ Protocol (`HistoricalBarReadRepository`,
# used by `HistoricalDataCoverageService`) and a WRITE Protocol
# (`HistoricalBarWriteRepository`, used only by
# `HistoricalDataPreparationService` after a provider fetch) — mirrors
# the existing `HistoricalMarketDataRepository`'s own explicit
# "read-only... ingestion is a separate concern" boundary
# (application/repositories/__init__.py) rather than widening that
# Protocol's contract. The concrete `DjangoHistoricalBarRepository`
# (infrastructure/persistence/repositories.py) satisfies BOTH of these
# Protocols AND the pre-existing `HistoricalMarketDataRepository`
# Protocol, so it can be handed directly to the unmodified
# `HistoricalMarketDataService`/`BacktestingService` for scanning once
# data is persisted — one concrete class, three narrow interfaces.
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


class HistoricalBarReadRepository(Protocol):
    def get_existing_timestamps(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> frozenset[datetime]:
        """Every bar-close timestamp already persisted for
        `instrument_id`/`timeframe` within `[start, end]` — used only for
        set-membership coverage checks, never as a bar's actual price
        data."""
        ...


class HistoricalBarWriteRepository(Protocol):
    def bulk_upsert(self, bars: tuple[Bar, ...], *, source: str) -> int:
        """Persists `bars`, upserting by the
        `(instrument_id, timeframe, bar_timestamp)` identity (Phase 2's
        uniqueness rule) — re-persisting an already-cached bar is a safe
        no-op, never a duplicate row. Returns the number of bars actually
        written (inserted or updated)."""
        ...
