# File: src/intraday/application/repositories/worker_runtime_status.py
#
# Checkpoint 64.3: the "persist or expose runtime state" Protocol - one
# row per market-data worker provider ("dhan"), written by the worker
# process, read by the API. Mirrors `ProviderConnectionStatusRepository`'s
# own established one-row-per-provider pattern (Checkpoint 22).
#
# Checkpoint 64.4 ADDS: the EFFECTIVE scanner state fields
# (`effective_*`) - what the worker actually applied from the desired
# `ScannerConfiguration`, recorded on THIS row rather than a new one
# (the desired/effective split is a column split within one provider's
# runtime facts, not two separate resources).
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
    effective_configuration_version: int
    effective_timeframe: str
    effective_strategy_ids: tuple[str, ...]
    effective_universe_requested_count: int
    effective_universe_subscribed_count: int


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

    def save_effective_scanner_state(
        self,
        provider: str,
        *,
        effective_configuration_version: int,
        effective_timeframe: str,
        effective_strategy_ids: list[str],
        effective_universe_requested_count: int,
        effective_universe_subscribed_count: int,
    ) -> None:
        """A separate write path from `save()` above - the worker calls
        this only when it actually RECONCILES against a (possibly
        unchanged) desired configuration, on a different cadence than
        health-tracker snapshots."""
        ...


__all__ = ["WorkerRuntimeStatusRecord", "WorkerRuntimeStatusRepository"]
