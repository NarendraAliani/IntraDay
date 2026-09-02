# tests/unit/application/services/test_market_data_worker_supervisor.py
#
# Checkpoint 67.12.2-H, Part 3: proves the bounded auto-restart
# supervisor's decision logic - a positive test (it restarts within its
# bound after observing the Part-1-fixed terminal FAILED state) and a
# negative test (it does NOT restart beyond --max-restarts). Every side
# effect is a fake/synthetic callable - `start_worker` never spawns a
# real process, `sleep` never actually waits - and `WorkerRuntimeStatus`
# is a real DB row the test flips directly to simulate a crash, exactly
# mirroring how the real worker process would leave it after Part 1's
# fix. NO real Dhan connection, NO real subprocess, anywhere in this
# file.
from __future__ import annotations

import datetime as dt

import pytest
from asgiref.sync import sync_to_async

from intraday.application.services.market_data_worker_supervisor import (
    supervise_market_data_worker,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

# Checkpoint 67.12.2-H: `transaction=True`, NOT the plain `django_db`
# mark - matching this checkpoint's own hard-won finding in
# `test_run_market_data_worker_command.py`. Every test here writes to
# `WorkerRuntimeStatus` from BOTH the main test thread (the pre-seed) AND
# `supervise_market_data_worker`'s own `sync_to_async`-wrapped writes (a
# real second DB connection). The plain `django_db` mark wraps the test
# in an atomic block/savepoint that never truly commits until teardown -
# the second connection then blocks forever trying to lock the same row.
# Reproduced and confirmed as a genuine deadlock during this checkpoint
# before this fix (two Postgres backends: one idle at "RELEASE
# SAVEPOINT", one hung on an UPDATE/INSERT of the same row).
pytestmark = pytest.mark.django_db(transaction=True)


def _clock(start: dt.datetime) -> tuple[list[dt.datetime], object]:
    """A fake, test-controlled clock - `now()` returns the current head of
    a mutable list the test advances explicitly, so session-end and
    poll-interval timing is deterministic, never real wall-clock time."""
    state = {"now": start}

    def now() -> dt.datetime:
        return state["now"]

    def advance(seconds: float) -> None:
        state["now"] = state["now"] + dt.timedelta(seconds=seconds)

    return state, (now, advance)  # type: ignore[return-value]


def test_supervisor_restarts_within_its_bound_after_a_crash() -> None:
    """Positive test: a single detected FAILED status triggers exactly one
    restart, well within max_restarts, and the run reaches its
    session-end and stops cleanly - proving the restart happens, not just
    that the bound is never exceeded."""
    repo = DjangoWorkerRuntimeStatusRepository()
    provider = "dhan"
    repo.save(
        provider,
        worker_state="STOPPED",
        token_state="VALID",
        watchdog_state="DISCONNECTED",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=0,
        last_error_safe="",
    )

    start = dt.datetime(2026, 9, 3, 4, 0, 0, tzinfo=dt.UTC)
    session_end = start + dt.timedelta(seconds=40)
    clock_state = {"now": start}

    def now() -> dt.datetime:
        return clock_state["now"]

    starts: list[int] = []
    stop_requested = {"called": False}
    archive_refreshed = {"called": False}
    sleeps: list[float] = []

    async def start_worker() -> None:
        starts.append(len(starts) + 1)
        # First start: simulate the worker running normally. It only
        # crashes (FAILED, exactly what Part 1's fix persists) after the
        # first restart is triggered below - simulated directly on the
        # DB row, never inferred.
        await sync_to_async(repo.save)(
            provider,
            worker_state="RUNNING",
            token_state="VALID",
            watchdog_state="HEALTHY",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=0,
            consecutive_failures=0,
            subscribed_instrument_count=15,
            last_error_safe="",
        )

    async def is_worker_alive() -> bool:
        return True

    async def request_session_end_stop() -> None:
        stop_requested["called"] = True
        await sync_to_async(repo.save)(
            provider,
            worker_state="STOPPED",
            token_state="VALID",
            watchdog_state="DISCONNECTED",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=1,
            consecutive_failures=0,
            subscribed_instrument_count=0,
            last_error_safe="",
        )

    async def wait_for_worker_exit() -> None:
        return None

    async def refresh_archive() -> None:
        archive_refreshed["called"] = True

    poll_count = {"n": 0}

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        poll_count["n"] += 1
        # Advance the fake clock so the loop makes real progress instead
        # of spinning forever against a clock that never moves.
        clock_state["now"] = clock_state["now"] + dt.timedelta(seconds=seconds)
        # After the very first poll (worker RUNNING, observed once),
        # simulate the crash: flip the DB row to FAILED, exactly what
        # Part 1's fix persists when the reconnect supervisor exhausts.
        if poll_count["n"] == 1:
            await sync_to_async(repo.save)(
                provider,
                worker_state="FAILED",
                token_state="VALID",
                watchdog_state="DISCONNECTED",
                last_packet_at=now(),
                last_bar_at=None,
                reconnect_count=5,
                consecutive_failures=5,
                subscribed_instrument_count=0,
                last_error_safe="reconnect_attempts_exhausted",
            )

    result = __import__("asyncio").run(
        supervise_market_data_worker(
            provider=provider,
            max_restarts=3,
            cooldown_seconds=1.0,
            session_end=session_end,
            poll_interval_seconds=5.0,
            status_repository=repo,
            start_worker=start_worker,
            is_worker_alive=is_worker_alive,
            request_session_end_stop=request_session_end_stop,
            wait_for_worker_exit=wait_for_worker_exit,
            refresh_archive=refresh_archive,
            sleep=sleep,
            now=now,
        )
    )

    assert len(starts) == 2, "expected exactly one restart (initial start + 1 restart)"
    assert result.restarts_used == 1
    assert result.stopped_cleanly is True
    assert result.max_restarts_exhausted is False
    assert stop_requested["called"] is True
    assert archive_refreshed["called"] is True
    restart_events = [e for e in result.log if e.event == "worker_restarted"]
    assert len(restart_events) == 1


def test_supervisor_never_restarts_beyond_max_restarts() -> None:
    """Negative test: the worker crashes repeatedly, faster than
    session-end - the supervisor must restart up to max_restarts times
    and then stop PERMANENTLY, never attempting a further restart, even
    though session-end has not been reached and more crashes keep being
    observed."""
    repo = DjangoWorkerRuntimeStatusRepository()
    provider = "dhan"
    repo.save(
        provider,
        worker_state="STOPPED",
        token_state="VALID",
        watchdog_state="DISCONNECTED",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=0,
        last_error_safe="",
    )

    start = dt.datetime(2026, 9, 3, 4, 0, 0, tzinfo=dt.UTC)
    # Session end far in the future relative to how fast this test's fake
    # clock advances via `sleep` below - the run must end because
    # max_restarts is exhausted, NOT because session_end arrived.
    session_end = start + dt.timedelta(hours=6)
    clock_state = {"now": start}

    def now() -> dt.datetime:
        return clock_state["now"]

    starts: list[int] = []

    async def start_worker() -> None:
        starts.append(len(starts) + 1)
        await sync_to_async(repo.save)(
            provider,
            worker_state="RUNNING",
            token_state="VALID",
            watchdog_state="HEALTHY",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=0,
            consecutive_failures=0,
            subscribed_instrument_count=15,
            last_error_safe="",
        )

    async def is_worker_alive() -> bool:
        return True

    async def request_session_end_stop() -> None:  # pragma: no cover - must never be called
        raise AssertionError("session-end stop should never be requested in this test")

    async def wait_for_worker_exit() -> None:  # pragma: no cover
        return None

    async def refresh_archive() -> None:  # pragma: no cover
        return None

    poll_count = {"n": 0}

    async def sleep(seconds: float) -> None:
        poll_count["n"] += 1
        clock_state["now"] = clock_state["now"] + dt.timedelta(seconds=seconds)
        # Every poll observes a fresh crash - a pathologically unstable
        # worker/network, exactly the scenario max_restarts exists to
        # bound.
        await sync_to_async(repo.save)(
            provider,
            worker_state="FAILED",
            token_state="VALID",
            watchdog_state="DISCONNECTED",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=5,
            consecutive_failures=5,
            subscribed_instrument_count=0,
            last_error_safe="reconnect_attempts_exhausted",
        )

    result = __import__("asyncio").run(
        supervise_market_data_worker(
            provider=provider,
            max_restarts=2,
            cooldown_seconds=1.0,
            session_end=session_end,
            poll_interval_seconds=5.0,
            status_repository=repo,
            start_worker=start_worker,
            is_worker_alive=is_worker_alive,
            request_session_end_stop=request_session_end_stop,
            wait_for_worker_exit=wait_for_worker_exit,
            refresh_archive=refresh_archive,
            sleep=sleep,
            now=now,
        )
    )

    # Initial start + exactly 2 restarts (the bound) - never a 3rd.
    assert len(starts) == 3
    assert result.restarts_used == 2
    assert result.max_restarts_exhausted is True
    assert result.stopped_cleanly is False
    restart_events = [e for e in result.log if e.event == "worker_restarted"]
    assert len(restart_events) == 2
    exhausted_events = [e for e in result.log if e.event == "max_restarts_exhausted"]
    assert len(exhausted_events) == 1
