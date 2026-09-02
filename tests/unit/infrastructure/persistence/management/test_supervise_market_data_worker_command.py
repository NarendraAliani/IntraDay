# tests/unit/infrastructure/persistence/management/test_supervise_market_data_worker_command.py
#
# Checkpoint 67.12.2-S, Part 3: proves `supervise_market_data_worker`
# runs PID-verified startup reconciliation BEFORE its own restart-
# decision loop ever polls `WorkerRuntimeStatus` - this is the command
# that runs unattended tomorrow, and its restart decisions depend on
# trusting this row more than any other caller does.
#
# The pure `supervise_market_data_worker()` core loop itself is
# monkeypatched to a trivial stub (already exhaustively tested against
# fakes in `test_market_data_worker_supervisor.py`) - this file's own
# job is narrower: prove the MANAGEMENT COMMAND wires reconciliation in
# at startup, without needing a real subprocess spawn or a real archive
# refresh. No real Dhan connection, no real subprocess, anywhere here.
from __future__ import annotations

import datetime as dt
import io

import pytest
from django.core.management import call_command

from intraday.infrastructure.persistence.management.commands import (
    supervise_market_data_worker as command_module,
)
from intraday.infrastructure.persistence.models import WorkerRuntimeStatus
from intraday.infrastructure.system import process_liveness

pytestmark = pytest.mark.django_db(transaction=True)


async def _fake_supervise_market_data_worker(**kwargs: object) -> object:
    from intraday.application.services.market_data_worker_supervisor import SupervisorResult

    return SupervisorResult(
        stopped_cleanly=True,
        restarts_used=0,
        max_restarts_exhausted=False,
        final_worker_state="FAILED",
        log=[],
    )


def test_supervisor_reconciles_a_stale_row_before_its_own_restart_loop_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    DEAD_PID = 999_998
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan",
        defaults={
            "worker_state": "RECONNECTING",
            "owner_pid": DEAD_PID,
            "owner_process_started_at": None,
            "owner_cmdline_safe": "python manage.py run_market_data_worker --provider dhan",
        },
    )

    def _dead_probe(pid: int) -> process_liveness.ProcessSnapshot | None:
        assert pid == DEAD_PID
        return None

    monkeypatch.setattr(command_module, "probe_process", _dead_probe)
    # The pure supervisor loop itself is stubbed - already covered by
    # `test_market_data_worker_supervisor.py` - so this test proves
    # ONLY the command's own startup wiring, never re-derives the loop's
    # restart/bound logic.
    monkeypatch.setattr(
        command_module, "supervise_market_data_worker", _fake_supervise_market_data_worker
    )

    out = io.StringIO()
    session_end = (dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=1)).isoformat()
    call_command(
        "supervise_market_data_worker",
        "--provider",
        "dhan",
        "--max-restarts",
        "0",
        "--cooldown-seconds",
        "0",
        "--session-end",
        session_end,
        stdout=out,
    )

    output = out.getvalue()
    assert "startup reconciliation: action=reconciled_stale" in output
    status = WorkerRuntimeStatus.objects.get(provider="dhan")
    # The stubbed loop never touches worker_state itself - so this value
    # is proof the command's OWN startup step, not the loop, wrote it.
    assert status.worker_state == "FAILED"
    assert "reconciled: stale status detected at startup" in status.last_error_safe


def test_supervisor_does_not_touch_a_row_that_verifiably_reflects_a_live_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_pid = 424_242
    started_at = dt.datetime(2026, 9, 2, 8, 0, 0, tzinfo=dt.UTC)
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan",
        defaults={
            "worker_state": "RUNNING",
            "last_error_safe": "",
            "owner_pid": real_pid,
            "owner_process_started_at": started_at,
            "owner_cmdline_safe": "python manage.py run_market_data_worker --provider dhan",
        },
    )

    def _alive_probe(pid: int) -> process_liveness.ProcessSnapshot | None:
        assert pid == real_pid
        return process_liveness.ProcessSnapshot(
            pid=real_pid,
            started_at=started_at,
            cmdline_safe="python manage.py run_market_data_worker --provider dhan",
        )

    monkeypatch.setattr(command_module, "probe_process", _alive_probe)
    monkeypatch.setattr(
        command_module, "supervise_market_data_worker", _fake_supervise_market_data_worker
    )

    out = io.StringIO()
    session_end = (dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=1)).isoformat()
    call_command(
        "supervise_market_data_worker",
        "--provider",
        "dhan",
        "--max-restarts",
        "0",
        "--cooldown-seconds",
        "0",
        "--session-end",
        session_end,
        stdout=out,
    )

    output = out.getvalue()
    assert "startup reconciliation: action=confirmed_alive" in output
    status = WorkerRuntimeStatus.objects.get(provider="dhan")
    assert status.worker_state == "RUNNING"
    assert status.last_error_safe == ""
