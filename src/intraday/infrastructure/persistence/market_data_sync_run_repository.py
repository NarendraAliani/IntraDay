# File: src/intraday/infrastructure/persistence/market_data_sync_run_repository.py
#
# Django ORM implementation of `MarketDataSyncRunRepository` - mirrors
# `historical_backtest_run_repository.py` exactly.
from __future__ import annotations

from datetime import date

from intraday.application.repositories.market_data_sync_run import MarketDataSyncRunSnapshot
from intraday.infrastructure.persistence.models import MarketDataSyncRun


def _to_snapshot(row: MarketDataSyncRun) -> MarketDataSyncRunSnapshot:
    return MarketDataSyncRunSnapshot(
        run_id=row.run_id,
        status=row.status,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_by=row.created_by,
        start_date=row.start_date,
        end_date=row.end_date,
        timeframe=row.timeframe,
        instrument_ids=tuple(row.instrument_ids),
        total_instruments=row.total_instruments,
        completed_instruments=row.completed_instruments,
        bars_fetched=row.bars_fetched,
        bars_persisted=row.bars_persisted,
        cache_hits=row.cache_hits,
        api_requests=row.api_requests,
        failed_instruments=tuple(row.failed_instruments),
        progress_percent=float(row.progress_percent),
        current_instrument=row.current_instrument,
        message=row.message,
    )


class DjangoMarketDataSyncRunRepository:
    def create(
        self,
        run_id: str,
        *,
        created_by: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        instrument_ids: list[str],
        total_instruments: int,
    ) -> None:
        MarketDataSyncRun.objects.create(
            run_id=run_id,
            created_by=created_by,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            instrument_ids=instrument_ids,
            total_instruments=total_instruments,
            status="QUEUED",
        )

    def update(self, run_id: str, **fields: object) -> None:
        MarketDataSyncRun.objects.filter(run_id=run_id).update(**fields)

    def get(self, run_id: str) -> MarketDataSyncRunSnapshot | None:
        row = MarketDataSyncRun.objects.filter(run_id=run_id).first()
        return _to_snapshot(row) if row is not None else None


__all__ = ["DjangoMarketDataSyncRunRepository"]
