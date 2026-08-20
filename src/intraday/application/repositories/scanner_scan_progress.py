# File: src/intraday/application/repositories/scanner_scan_progress.py
#
# Checkpoint 64.18 §2/§5: the "what is the scanner doing RIGHT NOW"
# Protocol - one row per provider ("dhan"), written ONLY by the worker's
# own scan loop, read by the API. Mirrors `WorkerRuntimeStatusRepository`'s
# established one-row-per-provider pattern exactly - never a second,
# competing worker-lifecycle model. `universe_remaining`/`progress_
# percent` are DELIBERATELY absent here - both are pure derivations
# (`total - processed`, `processed / total * 100`) computed by the
# reader (API view), never stored, so there is exactly one source of
# truth for the raw counters.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ScannerScanStatus(enum.Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    SCANNING = "SCANNING"
    COMPLETED = "COMPLETED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class ScannerScanProgressRecord:
    provider: str
    scan_id: str
    scan_started_at: datetime | None
    timeframe: str
    universe_total: int
    universe_processed: int
    current_instrument: str
    current_strategy: str
    strategies_total: int
    strategies_processed: int
    signals_found: int
    last_progress_at: datetime | None
    status: str
    last_error_safe: str


class ScannerScanProgressRepository(Protocol):
    def get(self, provider: str) -> ScannerScanProgressRecord | None: ...

    def start_scan(
        self,
        provider: str,
        *,
        scan_id: str,
        scan_started_at: datetime,
        timeframe: str,
        universe_total: int,
        strategies_total: int,
    ) -> None:
        """Called ONCE at the start of a new scan cycle - resets
        `universe_processed`/`strategies_processed`/`signals_found` to
        0 and sets `status=STARTING`."""
        ...

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
        """Called repeatedly DURING a scan - only the fields explicitly
        passed are updated (`None` leaves the stored value unchanged),
        `last_progress_at` is always bumped to now. The worker/scanner
        is the ONLY caller ever allowed to invoke this (§3) - never the
        frontend, never a timer."""
        ...

    def mark_idle(self, provider: str) -> None:
        """Called when the scanner is disabled (desired.enabled=False) -
        an honest IDLE state, distinct from a stuck/stale SCANNING."""
        ...


__all__ = [
    "ScannerScanProgressRecord",
    "ScannerScanProgressRepository",
    "ScannerScanStatus",
]
