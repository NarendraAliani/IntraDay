# File: src/intraday/application/services/worker_status_reconciliation.py
#
# Checkpoint 67.12.2-S: PID-verified startup reconciliation.
#
# 67.12.2-H (commit 4e38fdd) closed the proximate cause of the row that
# froze at RECONNECTING the morning of 2026-09-02: the in-process
# reconnect supervisor not persisting a terminal state on exhaustion.
# But that fix only ever fires if the worker process is still running
# ITS OWN Python code - it does nothing for external kill, crash, OOM,
# or a host reboot, every one of which leaves `WorkerRuntimeStatus`
# claiming RUNNING/RECONNECTING with nobody left to correct it. This
# morning's real row needed an explicit, manually-authorized one-time
# correction (67.12.2-F) precisely because nothing verified the row
# against OS reality.
#
# This module is that verification, as a pure, independently-testable
# core: given a `WorkerRuntimeStatusRecord` and a way to ask "is this
# PID genuinely alive, and is it the SAME process" (a caller-supplied
# `probe_process` callable - a fake in tests, the real
# `infrastructure.system.process_liveness.probe_process` in
# production), it decides whether the row's active claim is trustworthy
# and, if not, corrects it to a clearly-labeled RECONCILED terminal
# state - distinguishable in `last_error_safe` from a genuine in-process
# FAILED (67.12.2-H's own mechanism), so a future reader can tell which
# caught it.
#
# Deliberately does NOT touch any EXISTING gate that reads this row
# (e.g. a Part-0-style literal `worker_state` check) - it runs BEFORE
# such a gate, making the underlying data trustworthy, never loosening
# what reads it afterwards.
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from intraday.application.repositories.worker_runtime_status import (
    WorkerRuntimeStatusRecord,
    WorkerRuntimeStatusRepository,
)


class ProcessSnapshot(Protocol):
    """Structural-only contract for what a `probe_process` callable
    returns - deliberately NOT importing
    `infrastructure.system.process_liveness.ProcessSnapshot` here
    (`tests/unit/architecture/test_api_boundaries.py` mechanically
    forbids `application/services` importing anything under
    `infrastructure`). The real dataclass in that infrastructure module
    already satisfies this Protocol structurally - no adapter needed,
    matching this project's established "application defines the
    Protocol, infrastructure supplies a structurally-compatible
    implementation" pattern (`WorkerRuntimeStatusRepository` itself)."""

    started_at: dt.datetime | None
    cmdline_safe: str

RECONCILED_STALE_REASON = "reconciled: stale status detected at startup, PID not alive"
"""Deliberately distinct wording from any genuine in-process
`mark_failed()` reason (e.g. "reconnect_attempts_exhausted") - a future
reader must be able to tell "the process itself observed a genuine
failure" (67.12.2-H) apart from "nobody was left to say so; a later
startup verified the OS and found no such process" (this checkpoint)."""

_ACTIVE_CLAIM_STATES = frozenset({"RUNNING", "RECONNECTING", "CONNECTING"})
"""The states this row can claim that assert "a real OS process
currently owns this connection." STOPPED/FAILED/AUTH_FAILED/
TOKEN_EXPIRED are already terminal/inactive and need no reconciliation -
correcting them would not change anything an existing gate reads."""

_START_TIME_TOLERANCE = dt.timedelta(seconds=2)
"""`GetProcessTimes` and this row's own `owner_process_started_at` are
independently-sourced timestamps (one read live from the OS, one
persisted earlier from the SAME probe at connect time) - a small
tolerance absorbs sub-second rounding without weakening the check: a
genuine PID-reuse case has a start time that differs by seconds,
minutes, hours, or more, never a sub-2-second jitter."""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    provider: str
    action: str
    """One of: "no_row", "not_active", "confirmed_alive",
    "reconciled_stale"."""
    reason: str


def reconcile_worker_runtime_status(
    provider: str,
    *,
    status_repository: WorkerRuntimeStatusRepository,
    probe_process: Callable[[int], ProcessSnapshot | None],
    now: Callable[[], dt.datetime],
) -> ReconciliationResult:
    """Called at the START of `run_market_data_worker` and
    `supervise_market_data_worker`, before either makes any decision
    based on existing `WorkerRuntimeStatus` state.

    Never weakens what a LATER gate reads - it only ever moves a row
    from an unverifiable active claim to a correctly-labeled FAILED
    when the OS itself disagrees; a row that IS verifiably alive, or
    that already claims a terminal state, is left byte-for-byte
    unchanged."""
    status = status_repository.get(provider)
    if status is None:
        return ReconciliationResult(provider, "no_row", "no WorkerRuntimeStatus row exists yet")

    if status.worker_state not in _ACTIVE_CLAIM_STATES:
        return ReconciliationResult(
            provider,
            "not_active",
            f"worker_state={status.worker_state!r} is already inactive/terminal - nothing to reconcile",
        )

    if status.owner_pid is None:
        return _reconcile(status_repository, provider, now(), "row claims active but no owner_pid was ever recorded")

    live = probe_process(status.owner_pid)
    if live is None:
        return _reconcile(
            status_repository,
            provider,
            now(),
            f"owner_pid={status.owner_pid} is not alive on this host",
        )

    if not _same_process(status, live):
        return _reconcile(
            status_repository,
            provider,
            now(),
            f"owner_pid={status.owner_pid} is alive but belongs to a different process "
            "(start time/command line mismatch - PID reuse)",
        )

    return ReconciliationResult(
        provider, "confirmed_alive", f"owner_pid={status.owner_pid} verified alive and matches the recorded identity"
    )


def _same_process(status: WorkerRuntimeStatusRecord, live: ProcessSnapshot) -> bool:
    """PID-reuse disambiguation (Part 1.3's explicit requirement): a
    live PID is not itself proof of identity. Start-time comparison is
    the PRIMARY signal (always available from `GetProcessTimes` for a
    genuinely alive process) - a recorded start time that does not
    match the live process's actual creation time, within tolerance,
    means the PID was reused by something else. Command-line
    containment is a SECOND, best-effort signal used only when both
    sides actually have one to compare (either side being empty, e.g. a
    cmdline query that failed, never itself fails the match - it simply
    isn't used as evidence)."""
    if status.owner_process_started_at is not None and live.started_at is not None:
        delta = abs((status.owner_process_started_at - live.started_at).total_seconds())
        if delta > _START_TIME_TOLERANCE.total_seconds():
            return False

    if status.owner_cmdline_safe and live.cmdline_safe:
        if "market_data_worker" not in live.cmdline_safe and "market_data_worker" not in status.owner_cmdline_safe:
            return False

    return True


def _reconcile(
    status_repository: WorkerRuntimeStatusRepository, provider: str, checked_at: dt.datetime, detail: str
) -> ReconciliationResult:
    status_repository.reconcile_stale(provider, last_error_safe=RECONCILED_STALE_REASON, checked_at=checked_at)
    return ReconciliationResult(provider, "reconciled_stale", detail)


__all__ = ["ReconciliationResult", "RECONCILED_STALE_REASON", "reconcile_worker_runtime_status"]
