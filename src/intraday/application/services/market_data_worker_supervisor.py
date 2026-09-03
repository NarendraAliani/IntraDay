# File: src/intraday/application/services/market_data_worker_supervisor.py
#
# Checkpoint 67.12.2-H, Part 3: the bounded auto-restart supervisor
# tomorrow's unattended full-session capture (§65.13) needs. Today
# (67.12.2-E) two live crashes went undetected for a combined ~23+
# minutes because nothing watched `WorkerRuntimeStatus` above the
# worker's own in-process 5-attempt reconnect ceiling - a human had to
# notice by accident. This module is the missing outer loop.
#
# Deliberately NOT a generic process-supervision framework - it does
# exactly what THIS command needs: poll one `WorkerRuntimeStatus` row,
# restart the worker via a caller-supplied factory when it observes the
# Part-1-fixed terminal FAILED state, bounded by `max_restarts`, and
# stop cleanly at `session_end` reusing the EXISTING stop-request +
# `market_data_archive --refresh` mechanism (Checkpoint 64.73/67.12.2-C/E)
# rather than inventing a new one.
#
# Pure core, no subprocess/CLI here (that lives in the management
# command) - `start_worker`/`is_worker_alive`/`stop_worker` are
# caller-supplied callables so this loop is testable against the
# existing fake/synthetic harness (a test-controlled `WorkerRuntimeStatus`
# row and a fake worker-process double) with NO real Dhan connection and
# NO real subprocess spawn required to prove the restart-bound logic.
from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from asgiref.sync import sync_to_async

from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRepository
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

# States that mean "the worker process is genuinely gone and nothing will
# bring it back on its own" - restarting is the right response ONLY for
# FAILED (a bounded-reconnect exhaustion, per Part 1's fix - the disconnect
# itself may well be transient). AUTH_FAILED/TOKEN_EXPIRED are terminal
# for a DIFFERENT reason (a bad credential) that a process restart cannot
# fix and would just burn a restart slot on a guaranteed-repeat failure -
# those stop the supervisor immediately, same "report, don't improvise
# past the bound" discipline as everywhere else in this project.
_RESTART_ON = frozenset({WorkerState.FAILED.value})
_STOP_IMMEDIATELY_ON = frozenset({WorkerState.AUTH_FAILED.value, WorkerState.TOKEN_EXPIRED.value})


@dataclass(slots=True)
class SupervisorLogEntry:
    at: dt.datetime
    event: str
    detail: str


@dataclass(slots=True)
class SupervisorResult:
    stopped_cleanly: bool
    restarts_used: int
    max_restarts_exhausted: bool
    final_worker_state: str | None
    log: list[SupervisorLogEntry] = field(default_factory=list)


async def supervise_market_data_worker(
    *,
    provider: str,
    max_restarts: int,
    cooldown_seconds: float,
    session_end: dt.datetime,
    poll_interval_seconds: float,
    status_repository: WorkerRuntimeStatusRepository,
    start_worker: Callable[[], Awaitable[None]],
    is_worker_alive: Callable[[], Awaitable[bool]],
    request_session_end_stop: Callable[[], Awaitable[None]],
    wait_for_worker_exit: Callable[[], Awaitable[None]],
    refresh_archive: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]],
    now: Callable[[], dt.datetime],
) -> SupervisorResult:
    """The bounded auto-restart loop. Every side effect (spawning the
    worker, checking liveness, requesting the session-end stop, waiting
    for exit, refreshing the archive, sleeping, reading the clock) is a
    caller-supplied callable - real ones for the management command,
    fakes for the test suite - so this function contains ONLY the
    poll/restart/bound decision logic, independently testable without a
    real subprocess or a real Dhan connection.
    """
    log: list[SupervisorLogEntry] = []
    restarts_used = 0

    def _log(event: str, detail: str) -> None:
        log.append(SupervisorLogEntry(at=now(), event=event, detail=detail))

    _log("start", f"provider={provider} max_restarts={max_restarts} cooldown_seconds={cooldown_seconds}")
    await start_worker()
    _log("worker_started", "initial start")

    while True:
        if now() >= session_end:
            _log("session_end_reached", f"session_end={session_end.isoformat()}")
            await request_session_end_stop()
            _log("stop_requested", "process-independent stop request (Checkpoint 64.73 mechanism)")
            await wait_for_worker_exit()
            _log("worker_exited", "clean shutdown observed")
            await refresh_archive()
            _log("archive_refreshed", "market_data_archive --refresh equivalent")
            status = await sync_to_async(status_repository.get)(provider)
            return SupervisorResult(
                stopped_cleanly=True,
                restarts_used=restarts_used,
                max_restarts_exhausted=False,
                final_worker_state=status.worker_state if status is not None else None,
                log=log,
            )

        # Checkpoint 67.12.2-H: `WorkerRuntimeStatusRepository.get()` is a
        # plain (sync) Django ORM call - wrapped in `sync_to_async` because
        # this loop itself runs inside a real `asyncio` event loop
        # (matching every other DB access from async code elsewhere in
        # this project, e.g. `run_market_data_worker.py`'s own
        # `sync_to_async(...)` calls).
        status = await sync_to_async(status_repository.get)(provider)
        worker_state = status.worker_state if status is not None else None

        if worker_state in _STOP_IMMEDIATELY_ON:
            _log(
                "stopping_permanently",
                f"worker_state={worker_state} is a credential problem, not a "
                "restart-recoverable failure - restarting would just repeat it.",
            )
            return SupervisorResult(
                stopped_cleanly=False,
                restarts_used=restarts_used,
                max_restarts_exhausted=False,
                final_worker_state=worker_state,
                log=log,
            )

        if worker_state in _RESTART_ON:
            reason_safe = status.last_error_safe if status is not None else ""
            if restarts_used >= max_restarts:
                _log(
                    "max_restarts_exhausted",
                    f"worker_state=FAILED (reason={reason_safe!r}) but "
                    f"restarts_used={restarts_used} >= max_restarts={max_restarts} - "
                    "stopping permanently, no further restart attempted.",
                )
                return SupervisorResult(
                    stopped_cleanly=False,
                    restarts_used=restarts_used,
                    max_restarts_exhausted=True,
                    final_worker_state=worker_state,
                    log=log,
                )
            _log(
                "crash_detected",
                f"worker_state=FAILED (reason={reason_safe!r}) - "
                f"cooling down {cooldown_seconds}s before restart "
                f"{restarts_used + 1}/{max_restarts}.",
            )
            await sleep(cooldown_seconds)
            restarts_used += 1
            await start_worker()
            _log("worker_restarted", f"restart {restarts_used}/{max_restarts}")
            # Checkpoint LIVE-1-INSTRUMENT, Part 3: a grace period BEFORE
            # the next poll, not just before the restart. Without this,
            # the loop fell straight back to the top and polled
            # `WorkerRuntimeStatus` again with ZERO elapsed time - a real
            # subprocess spawn/Django-startup/credential-fetch sequence
            # needs real wall-clock time to overwrite its own row away
            # from the PREVIOUS process's terminal FAILED state
            # (`run_market_data_worker.py::_run_dhan`'s own long list of
            # `await sync_to_async(...)` calls before its first
            # `health_tracker.persist()`), so that stale FAILED read was
            # being mistaken for a brand-new crash - proven by
            # `test_a_stale_failed_row_after_restart_produces_a_phantom_
            # second_crash_detected`. `poll_interval_seconds` is reused
            # deliberately rather than inventing a new tunable: it is
            # already this loop's own answer to "how long is a reasonable
            # gap before checking status again," and reusing it keeps
            # `--max-restarts`/cooldown semantics completely untouched,
            # per this checkpoint's own prohibition.
            await sleep(poll_interval_seconds)
            continue

        await sleep(poll_interval_seconds)


__all__ = ["SupervisorLogEntry", "SupervisorResult", "supervise_market_data_worker"]
