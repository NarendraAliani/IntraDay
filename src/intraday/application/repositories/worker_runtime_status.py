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
    # Checkpoint 67.12.2-S: the PID-reconciliation anchor. Defaulted
    # (unlike every other field on this record) because this dataclass
    # is constructed directly, with keyword args and no default values
    # of their own, by pre-existing call sites throughout the test
    # suite (`test_live_paper_session.py`,
    # `test_live_paper_readiness_checklist.py`) that predate this
    # checkpoint and have no reason to know about worker-ownership
    # tracking. Frozen dataclasses only require trailing fields to
    # carry defaults, which these three already are - no reordering
    # needed. Real callers (`DjangoWorkerRuntimeStatusRepository`)
    # always pass explicit values read from the DB row; only
    # `None`/`""` here means "not populated by an owner-agnostic
    # caller," never a real ownership claim.
    owner_pid: int | None = None
    owner_process_started_at: datetime | None = None
    owner_cmdline_safe: str = ""


@dataclass(frozen=True, slots=True)
class WorkerStopRequest:
    """Checkpoint 64.73: a pending, PROCESS-INDEPENDENT request that the
    named worker stop. Carried on the worker's own runtime-status row
    rather than delivered as an OS signal - see
    `models.py::WorkerRuntimeStatus.stop_requested_at` for why 64.72's
    three signal-based attempts could not work on Windows."""

    provider: str
    requested_at: datetime
    requested_by: str
    reason_safe: str


class WorkerRuntimeStatusRepository(Protocol):
    def get(self, provider: str) -> WorkerRuntimeStatusRecord | None: ...

    def request_stop(
        self, provider: str, *, requested_at: datetime, requested_by: str, reason_safe: str
    ) -> None:
        """Records a stop request. Idempotent: requesting a stop twice
        leaves exactly one pending request."""
        ...

    def get_stop_request(self, provider: str) -> WorkerStopRequest | None:
        """The pending stop request, or `None`. Polled by the running
        worker; returns `None` once the request has been cleared."""
        ...

    def clear_stop_request(self, provider: str) -> None:
        """Clears any pending request. Called by the worker BOTH at
        startup (so a stale request left over from a previous run can
        never instantly kill a freshly started worker) and once a
        request has been honoured."""
        ...

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
        owner_pid: int | None = None,
        owner_process_started_at: datetime | None = None,
        owner_cmdline_safe: str = "",
    ) -> None: ...

    def reconcile_stale(
        self, provider: str, *, last_error_safe: str, checked_at: datetime
    ) -> None:
        """Checkpoint 67.12.2-S: overwrites ONLY `worker_state` (to
        `FAILED`) and `last_error_safe` on an EXISTING row, leaving
        every other column (owner_pid, effective_*, etc.) untouched -
        called by `worker_status_reconciliation.py` when a row claims
        RUNNING/RECONNECTING but the recorded OS process is not
        genuinely alive. Never called on a row that does not already
        exist."""
        ...

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


__all__ = [
    "WorkerRuntimeStatusRecord",
    "WorkerRuntimeStatusRepository",
    "WorkerStopRequest",
]
