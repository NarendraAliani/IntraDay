# tests/unit/application/services/test_worker_status_reconciliation.py
#
# Checkpoint 67.12.2-S, Part 2: proves PID-verified startup
# reconciliation against a REAL `WorkerRuntimeStatus` row (the Django
# ORM repository, exactly like the row a real worker process writes),
# using a FAKE `probe_process` callable - no real OS process is ever
# spawned or killed, no real Dhan connection anywhere in this file.
#
# Three cases, per the checkpoint directive:
#   1. positive - a stale row (dead/nonexistent PID) is corrected to the
#      reconciled terminal state BEFORE any other startup logic runs.
#   2. negative - a row correctly reflecting a still-alive process is
#      NOT force-healed; reconciliation never overwrites an accurate row.
#   3. PID-reuse - a row's recorded PID is alive but belongs to an
#      unrelated process (mismatched start time/cmdline) - still
#      correctly treated as stale, never mistaken for the real worker.
from __future__ import annotations

import datetime as dt

import pytest

from intraday.application.services.worker_status_reconciliation import (
    RECONCILED_STALE_REASON,
    reconcile_worker_runtime_status,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)
from intraday.infrastructure.system.process_liveness import ProcessSnapshot

pytestmark = pytest.mark.django_db

NOW = dt.datetime(2026, 9, 2, 9, 0, 0, tzinfo=dt.UTC)
REAL_START = dt.datetime(2026, 9, 2, 8, 55, 0, tzinfo=dt.UTC)


def _seed(
    repo: DjangoWorkerRuntimeStatusRepository,
    *,
    provider: str = "dhan",
    worker_state: str = "RECONNECTING",
    owner_pid: int | None = 424242,
    owner_process_started_at: dt.datetime | None = REAL_START,
    owner_cmdline_safe: str = "python manage.py run_market_data_worker --provider dhan",
) -> None:
    repo.save(
        provider,
        worker_state=worker_state,
        token_state="VALID",
        watchdog_state="DISCONNECTED",
        last_packet_at=NOW - dt.timedelta(minutes=30),
        last_bar_at=None,
        reconnect_count=3,
        consecutive_failures=5,
        subscribed_instrument_count=12,
        last_error_safe="connection_lost:close_code=1006",
        owner_pid=owner_pid,
        owner_process_started_at=owner_process_started_at,
        owner_cmdline_safe=owner_cmdline_safe,
    )


def test_stale_row_dead_pid_is_reconciled_to_failed_before_anything_else() -> None:
    """Case 1 (positive): today's real scenario - a row frozen at
    RECONNECTING whose owning process is genuinely gone (crash/kill/OOM/
    reboot, none of which 67.12.2-H's fix can catch). Reconciliation
    must correct it, with the distinguishable reconciled-not-genuine
    reason string."""
    repo = DjangoWorkerRuntimeStatusRepository()
    _seed(repo, worker_state="RECONNECTING", owner_pid=555555)  # never alive on this host

    def probe_process(pid: int) -> ProcessSnapshot | None:
        assert pid == 555555
        return None  # not alive

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )

    assert result.action == "reconciled_stale"
    row = repo.get("dhan")
    assert row is not None
    assert row.worker_state == "FAILED"
    assert row.last_error_safe == RECONCILED_STALE_REASON


def test_a_genuinely_alive_matching_process_is_never_force_healed() -> None:
    """Case 2 (negative): the row is telling the truth - the recorded
    PID is alive, its start time matches what was recorded, and its
    command line is a real worker process. Reconciliation must leave it
    completely untouched."""
    repo = DjangoWorkerRuntimeStatusRepository()
    _seed(
        repo,
        worker_state="RUNNING",
        owner_pid=777777,
        owner_process_started_at=REAL_START,
        owner_cmdline_safe="python manage.py run_market_data_worker --provider dhan",
    )

    def probe_process(pid: int) -> ProcessSnapshot | None:
        assert pid == 777777
        return ProcessSnapshot(
            pid=777777,
            started_at=REAL_START,
            cmdline_safe="python manage.py run_market_data_worker --provider dhan",
        )

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )

    assert result.action == "confirmed_alive"
    row = repo.get("dhan")
    assert row is not None
    assert row.worker_state == "RUNNING"  # completely unchanged
    assert row.last_error_safe == "connection_lost:close_code=1006"  # unchanged


def test_pid_reuse_is_correctly_treated_as_stale_not_the_real_worker() -> None:
    """Case 3 (PID reuse): the recorded PID is alive RIGHT NOW, but it
    is not the same process that wrote the row - a different process
    started much later (or earlier) and with an unrelated command line
    happens to have been assigned the same OS PID. Must be reconciled,
    exactly like a genuinely dead PID - a live-but-wrong PID is not
    proof the real worker is still running."""
    repo = DjangoWorkerRuntimeStatusRepository()
    _seed(
        repo,
        worker_state="RECONNECTING",
        owner_pid=888888,
        owner_process_started_at=REAL_START,
        owner_cmdline_safe="python manage.py run_market_data_worker --provider dhan",
    )

    def probe_process(pid: int) -> ProcessSnapshot | None:
        assert pid == 888888
        # A DIFFERENT process now alive under the same PID: started
        # hours later, with an unrelated command line (e.g. a notepad
        # or unrelated python.exe instance, not this project's worker).
        return ProcessSnapshot(
            pid=888888,
            started_at=REAL_START + dt.timedelta(hours=6),
            cmdline_safe="python -m http.server 8000",
        )

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )

    assert result.action == "reconciled_stale"
    assert "PID reuse" in result.reason
    row = repo.get("dhan")
    assert row is not None
    assert row.worker_state == "FAILED"
    assert row.last_error_safe == RECONCILED_STALE_REASON


def test_a_terminal_row_is_never_touched_no_active_claim_to_verify() -> None:
    """A row already claiming FAILED/STOPPED needs no reconciliation -
    nothing here should ever run a probe or write anything for a row
    that makes no active claim in the first place."""
    repo = DjangoWorkerRuntimeStatusRepository()
    _seed(repo, worker_state="STOPPED", owner_pid=None, owner_process_started_at=None)

    def probe_process(pid: int) -> ProcessSnapshot | None:
        raise AssertionError("probe_process must never be called for an inactive row")

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )

    assert result.action == "not_active"
    row = repo.get("dhan")
    assert row is not None
    assert row.worker_state == "STOPPED"


def test_active_row_with_no_recorded_pid_is_reconciled() -> None:
    """A row claiming RUNNING but with no `owner_pid` ever recorded
    (e.g. written before this checkpoint's field existed) is exactly as
    unverifiable as a dead PID - it must be reconciled, never trusted by
    default."""
    repo = DjangoWorkerRuntimeStatusRepository()
    _seed(repo, worker_state="RUNNING", owner_pid=None, owner_process_started_at=None)

    def probe_process(pid: int) -> ProcessSnapshot | None:
        raise AssertionError("no pid was recorded - probe_process must never be called")

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )

    assert result.action == "reconciled_stale"
    row = repo.get("dhan")
    assert row is not None
    assert row.worker_state == "FAILED"
    assert row.last_error_safe == RECONCILED_STALE_REASON


def test_no_row_at_all_is_a_no_op() -> None:
    repo = DjangoWorkerRuntimeStatusRepository()

    def probe_process(pid: int) -> ProcessSnapshot | None:
        raise AssertionError("no row exists - probe_process must never be called")

    result = reconcile_worker_runtime_status(
        "dhan", status_repository=repo, probe_process=probe_process, now=lambda: NOW
    )
    assert result.action == "no_row"
