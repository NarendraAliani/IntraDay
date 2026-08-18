# File: src/intraday/application/repositories/market_data_sync_run.py
#
# Follow-up to Checkpoint 63.x: the `MarketDataSyncRun` persistence
# Protocol - the same "mutable job state" shape
# `historical_backtest_run.py`'s own Protocol already established,
# reused deliberately rather than inventing a second convention.
# `timeframes` is plural - one run can cover multiple timeframes at
# once (an explicit, approved UI decision - see
# HistoricalMarketDataCard.tsx), each instrument x timeframe pair
# counted as one "combination" of progress.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MarketDataSyncRunSnapshot:
    run_id: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    start_date: date
    end_date: date
    timeframes: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    total_combinations: int
    completed_combinations: int
    bars_fetched: int
    bars_persisted: int
    cache_hits: int
    api_requests: int
    failed_combinations: tuple[dict[str, str], ...]
    progress_percent: float
    current_instrument: str
    current_timeframe: str
    message: str


class MarketDataSyncRunRepository(Protocol):
    def create(
        self,
        run_id: str,
        *,
        created_by: str,
        start_date: date,
        end_date: date,
        timeframes: list[str],
        instrument_ids: list[str],
        total_combinations: int,
    ) -> None: ...

    def update(self, run_id: str, **fields: object) -> None:
        """Partial update of any `MarketDataSyncRun` field by name - the
        orchestrator's one write path for progress reporting."""
        ...

    def get(self, run_id: str) -> MarketDataSyncRunSnapshot | None: ...


__all__ = ["MarketDataSyncRunSnapshot", "MarketDataSyncRunRepository"]
