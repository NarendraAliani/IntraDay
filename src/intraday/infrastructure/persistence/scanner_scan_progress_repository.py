# File: src/intraday/infrastructure/persistence/scanner_scan_progress_repository.py
#
# Checkpoint 64.18: Django ORM implementation of
# `ScannerScanProgressRepository` - mirrors `worker_runtime_status_
# repository.py`'s own established "get_or_create the singleton row,
# update only the fields the caller actually supplies" pattern exactly.
from __future__ import annotations

import datetime as dt

from intraday.application.repositories.scanner_scan_progress import ScannerScanProgressRecord
from intraday.infrastructure.persistence.models import ScannerScanProgress


def _to_record(row: ScannerScanProgress) -> ScannerScanProgressRecord:
    return ScannerScanProgressRecord(
        provider=row.provider,
        scan_id=row.scan_id,
        scan_started_at=row.scan_started_at,
        timeframe=row.timeframe,
        universe_total=row.universe_total,
        universe_processed=row.universe_processed,
        current_instrument=row.current_instrument,
        current_strategy=row.current_strategy,
        strategies_total=row.strategies_total,
        strategies_processed=row.strategies_processed,
        signals_found=row.signals_found,
        last_progress_at=row.last_progress_at,
        status=row.status,
        last_error_safe=row.last_error_safe,
    )


class DjangoScannerScanProgressRepository:
    def get(self, provider: str) -> ScannerScanProgressRecord | None:
        row = ScannerScanProgress.objects.filter(provider=provider).first()
        return _to_record(row) if row is not None else None

    def start_scan(
        self,
        provider: str,
        *,
        scan_id: str,
        scan_started_at: dt.datetime,
        timeframe: str,
        universe_total: int,
        strategies_total: int,
    ) -> None:
        ScannerScanProgress.objects.update_or_create(
            provider=provider,
            defaults={
                "scan_id": scan_id,
                "scan_started_at": scan_started_at,
                "timeframe": timeframe,
                "universe_total": universe_total,
                "universe_processed": 0,
                "current_instrument": "",
                "current_strategy": "",
                "strategies_total": strategies_total,
                "strategies_processed": 0,
                "signals_found": 0,
                "last_progress_at": scan_started_at,
                "status": "STARTING",
                "last_error_safe": "",
            },
        )

    def update_progress(
        self,
        provider: str,
        *,
        status: str,
        current_instrument: str = "",
        current_strategy: str = "",
        universe_processed: int | None = None,
        strategies_processed: int | None = None,
        signals_found: int | None = None,
        last_error_safe: str = "",
    ) -> None:
        row, _created = ScannerScanProgress.objects.get_or_create(provider=provider)
        row.status = status
        if current_instrument:
            row.current_instrument = current_instrument
        if current_strategy:
            row.current_strategy = current_strategy
        if universe_processed is not None:
            row.universe_processed = universe_processed
        if strategies_processed is not None:
            row.strategies_processed = strategies_processed
        if signals_found is not None:
            row.signals_found = signals_found
        if last_error_safe:
            row.last_error_safe = last_error_safe
        row.last_progress_at = dt.datetime.now(tz=dt.UTC)
        row.save()

    def mark_idle(self, provider: str) -> None:
        row, _created = ScannerScanProgress.objects.get_or_create(provider=provider)
        row.status = "IDLE"
        row.current_instrument = ""
        row.current_strategy = ""
        row.last_progress_at = dt.datetime.now(tz=dt.UTC)
        row.save()


__all__ = ["DjangoScannerScanProgressRepository"]
