# File: src/intraday/infrastructure/market_data_providers/dhan/worker_health_tracker.py
#
# Checkpoint 64.3: THE truthful-health fix the review named as the
# highest-priority, safety-critical gap - `run_market_data_worker.py`'s
# `--provider dhan` path previously passed `connection_is_healthy=True`
# unconditionally (Checkpoint 64.2's own honest disclosure). A bar must
# never be promoted to TRADING_GRADE_BAR just because a process happens
# to be running - it must reflect the REAL worker/token/feed state.
#
# Uses the EXISTING watchdog evaluator (`control_plane.market_data_watchdog`,
# Checkpoint 64.1) - never a second evaluator. This class's only job is
# bookkeeping: recording the raw facts (last packet/bar instants, the
# worker's own state-machine transitions, reconnect/failure counts) that
# `evaluate_market_data_watchdog()` already knows how to classify, then
# exposing ONE cheap `is_healthy(now)` boolean the signal pipeline can
# call before every promotion decision.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRepository
from intraday.control_plane.market_data_watchdog.contracts import (
    MarketDataWatchdogSnapshot,
    MarketDataWatchdogState,
)
from intraday.control_plane.market_data_watchdog.evaluator import evaluate_market_data_watchdog
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState


@dataclass(slots=True)
class WorkerHealthTracker:
    """Owned by the worker command (composition root), mutated as real
    events happen (a packet arrives, a bar closes, a connection is
    lost) - never a passive/derived object, matching this project's own
    "every state change follows a real action" discipline
    (`HistoricalBacktestRunOrchestrator`'s own progress-engine
    precedent)."""

    token_state: str = "UNCONFIGURED"
    worker_state: WorkerState = WorkerState.STOPPED
    last_packet_at: datetime | None = None
    last_bar_at: datetime | None = None
    reconnect_count: int = 0
    consecutive_failures: int = 0
    last_error_safe: str = ""
    subscribed_instrument_count: int = 0
    owner_pid: int | None = None
    """Checkpoint 67.12.2-S: the OS PID of the process this tracker
    belongs to - the anchor `worker_status_reconciliation.py` verifies
    against actual OS process state at a later startup. `None` only for
    a tracker that never had `mark_owner()` called (the synthetic
    fake/fake-ws providers, which never persist to a real provider row
    at all - see `_QuoteSink.__init__`'s own `runtime_status_provider`
    discipline)."""
    owner_process_started_at: datetime | None = None
    owner_cmdline_safe: str = ""

    def mark_owner(
        self, *, pid: int, started_at: datetime | None, cmdline_safe: str
    ) -> None:
        """Stamps this tracker with the identity of the real OS process
        that now owns it. Called ONCE, at composition-root time
        (`run_market_data_worker.py`'s `_run_dhan()`), from
        `infrastructure.system.process_liveness.current_process_identity()`
        - never computed inside this class itself, keeping this tracker
        free of any direct OS dependency and fully fake-testable."""
        self.owner_pid = pid
        self.owner_process_started_at = started_at
        self.owner_cmdline_safe = cmdline_safe

    def mark_token_state(self, token_state: str) -> None:
        self.token_state = token_state

    def mark_connecting(self) -> None:
        self.worker_state = WorkerState.CONNECTING

    def mark_connected(self, *, subscribed_instrument_count: int) -> None:
        self.worker_state = WorkerState.RUNNING
        self.subscribed_instrument_count = subscribed_instrument_count
        self.consecutive_failures = 0

    def mark_reconnecting(self, *, reason: str) -> None:
        self.worker_state = WorkerState.RECONNECTING
        self.reconnect_count += 1
        self.consecutive_failures += 1
        self.last_error_safe = reason

    def mark_stopped(self, *, reason: str = "stop_requested") -> None:
        """Checkpoint 64.71: the clean-shutdown counterpart to
        `mark_failed()`. A worker that was asked to stop and did so is
        NOT a failure and must not be recorded as one - it ends in
        `WorkerState.STOPPED`, so the persisted `WorkerRuntimeStatus`
        an operator (or the readiness API) reads afterwards says
        "stopped", never a stale "RUNNING" from the last successful
        connect. `consecutive_failures` is cleared for the same reason:
        a deliberate stop is not a failure streak."""
        self.worker_state = WorkerState.STOPPED
        self.consecutive_failures = 0
        self.last_error_safe = reason

    def mark_failed(self, worker_state: WorkerState, *, reason: str) -> None:
        self.worker_state = worker_state
        self.last_error_safe = reason

    def record_packet(self, *, now: datetime) -> None:
        self.last_packet_at = now

    def record_bar(self, *, now: datetime) -> None:
        self.last_bar_at = now

    def snapshot(self) -> MarketDataWatchdogSnapshot:
        return MarketDataWatchdogSnapshot(
            connection_state=self.worker_state.value,
            token_state=self.token_state,
            last_packet_at=self.last_packet_at,
            last_valid_quote_at=self.last_packet_at,
            last_bar_at=self.last_bar_at,
            reconnect_count=self.reconnect_count,
            consecutive_failures=self.consecutive_failures,
        )

    def evaluate(self, *, now: datetime) -> MarketDataWatchdogState:
        return evaluate_market_data_watchdog(self.snapshot(), now=now).state

    def is_healthy(self, *, now: datetime) -> bool:
        """THE one question the signal pipeline asks before ever
        promoting a bar - `RUNNING` alone is never sufficient; only a
        genuine `HEALTHY` watchdog classification counts. `DEGRADED`,
        `STALE`, `DISCONNECTED`, and `FAILED` are all "not healthy"
        (the review's own explicit list)."""
        return self.evaluate(now=now) is MarketDataWatchdogState.HEALTHY

    def persist(
        self, repository: WorkerRuntimeStatusRepository, *, provider: str, now: datetime
    ) -> None:
        """Checkpoint 64.3: the "persist or expose runtime state" gap -
        the worker process and the Django web process serving the API
        are separate OS processes; this is the ONE write path an
        operator-facing status API can read from. Called periodically
        by the worker (every aggregation pass), never by anything else -
        this tracker remains the single source of truth for its own
        in-memory state, this is just a snapshot of it."""
        repository.save(
            provider,
            worker_state=self.worker_state.value,
            token_state=self.token_state,
            watchdog_state=self.evaluate(now=now).value,
            last_packet_at=self.last_packet_at,
            last_bar_at=self.last_bar_at,
            reconnect_count=self.reconnect_count,
            consecutive_failures=self.consecutive_failures,
            subscribed_instrument_count=self.subscribed_instrument_count,
            last_error_safe=self.last_error_safe,
            owner_pid=self.owner_pid,
            owner_process_started_at=self.owner_process_started_at,
            owner_cmdline_safe=self.owner_cmdline_safe,
        )


__all__ = ["WorkerHealthTracker"]
