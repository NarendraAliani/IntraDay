# File: src/intraday/application/repositories/worker_runtime_status.py
#
# Checkpoint 64.3: the "persist or expose runtime state" Protocol - one
# row per market-data worker provider ("dhan"), written by the worker
# process, read by the API. Mirrors `ProviderConnectionStatusRepository`'s
# own established one-row-per-provider pattern (Checkpoint 22).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WorkerRuntimeStatusRecord:
    provider: str
    worker_state: str
    token_state: str
    watchdog_state: str
    last_packet_at: datetime | None
    last_bar_at: datetime | None
    reconnect_count: int
    consecutive_failures: int
    subscribed_instrument_count: int
    last_error_safe: str
    updated_at: datetime | None


class WorkerRuntimeStatusRepository(Protocol):
    def get(self, provider: str) -> WorkerRuntimeStatusRecord | None: ...

    def save(
        self,
        provider: str,
        *,
        worker_state: str,
        token_state: str,
        watchdog_state: str,
        last_packet_at: datetime | None,
        last_bar_at: datetime | None,
        reconnect_count: int,
        consecutive_failures: int,
        subscribed_instrument_count: int,
        last_error_safe: str,
    ) -> None: ...


__all__ = ["WorkerRuntimeStatusRecord", "WorkerRuntimeStatusRepository"]
