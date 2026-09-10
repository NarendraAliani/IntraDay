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


# --- Checkpoint LIVE-1-INSTRUMENT, Part 2/3: the phantom-restart race,
# confirmed, then fixed.
#
# The LIVE-1-POSTMORTEM checkpoint found two of five real crashes today
# logged `crash_detected` only 1-2ms after their own `worker_restarted`
# for the SAME restart cycle - far too fast to be a genuine 5-attempt
# reconnect-exhaustion sequence (which needs several real seconds per
# `reconnect_supervisor.py`'s own backoff formula).
#
# CONFIRMED AS A REAL RACE this checkpoint, not by reasoning alone: run
# against the PRE-FIX code, this exact test (same body, only the final
# assertion differed - it asserted the two events shared an identical
# timestamp) passed, proving `supervise_market_data_worker`'s loop did
# fire a second `crash_detected` with ZERO elapsed simulated time after
# `worker_restarted`, whenever `start_worker()` had not yet overwritten
# the row - exactly the shape a real subprocess spawn/Django-startup/
# credential-fetch sequence takes genuine wall-clock time to do (see
# `run_market_data_worker.py::_run_dhan`'s own long list of `await
# sync_to_async(...)` calls before its first `health_tracker.
# persist()`).
#
# FIXED this checkpoint: a grace-period `sleep(poll_interval_seconds)`
# now runs immediately after `worker_restarted` is logged, before the
# loop polls status again - giving the newly-spawned process real
# (simulated) time to overwrite its own row before the next read. This
# test now proves the FIX: even when `start_worker()` leaves the row
# stale, no phantom second `crash_detected` fires once the real process
# catches up during that grace window.
def test_phantom_restart_race_is_prevented_by_the_post_restart_grace_period() -> None:
    """Simulates the exact race the postmortem found - `start_worker()`
    for the restart does NOT reset the row - but has the newly-spawned
    process finish catching up (write RUNNING) DURING the new grace-
    period sleep, exactly as a real process's slightly-delayed startup
    would. Proves the fix: only ONE `crash_detected` occurs for the one
    genuine crash - no phantom second one from the stale read."""
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
    session_end = start + dt.timedelta(hours=6)
    clock_state = {"now": start}

    def now() -> dt.datetime:
        return clock_state["now"]

    starts: list[int] = []

    async def start_worker() -> None:
        starts.append(len(starts) + 1)
        if len(starts) == 1:
            # The FIRST start behaves like a real, healthy worker.
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
        else:
            # THE restart that would have reproduced the race:
            # deliberately leaves the row untouched (still FAILED from
            # the crash just detected) - exactly what a real subprocess
            # that hasn't finished Django/credential startup yet would
            # do. The row is instead updated below, from the grace-
            # period `sleep()` call itself - simulating the real
            # process finishing its startup DURING that window.
            pass

    async def is_worker_alive() -> bool:
        return True

    async def request_session_end_stop() -> None:
        await sync_to_async(repo.save)(
            provider,
            worker_state="STOPPED",
            token_state="VALID",
            watchdog_state="DISCONNECTED",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=0,
            consecutive_failures=0,
            subscribed_instrument_count=0,
            last_error_safe="",
        )

    async def wait_for_worker_exit() -> None:
        return None

    async def refresh_archive() -> None:
        return None

    poll_count = {"n": 0}

    async def sleep(seconds: float) -> None:
        poll_count["n"] += 1
        clock_state["now"] = clock_state["now"] + dt.timedelta(seconds=seconds)
        # sleep #1: the poll_interval sleep after the first (healthy)
        # poll - flip to FAILED to trigger the one genuine crash.
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
        # sleep #2: the cooldown sleep before the restart - row stays
        # FAILED (start_worker() itself deliberately leaves it so, per
        # above). sleep #3: THE new post-restart grace-period sleep -
        # this is where the real process "finishes catching up",
        # exactly as a real subprocess's delayed startup eventually
        # would, DURING the grace window rather than instantly.
        if poll_count["n"] == 3:
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
        # Advance the clock far enough past session_end after a few
        # cycles so the test terminates even if the fix somehow failed
        # to prevent further phantom crashes (defensive - the real
        # assertion is on the log shape).
        if poll_count["n"] >= 8:
            clock_state["now"] = session_end + dt.timedelta(seconds=1)

    result = __import__("asyncio").run(
        supervise_market_data_worker(
            provider=provider,
            max_restarts=10,
            cooldown_seconds=2.0,
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

    crash_events = [e for e in result.log if e.event == "crash_detected"]
    restart_events = [e for e in result.log if e.event == "worker_restarted"]

    # THE fix proof: exactly ONE crash_detected (the genuine one) and
    # exactly ONE worker_restarted - the stale-row read that would have
    # produced a second, phantom crash_detected immediately afterwards
    # (proven to occur on the pre-fix code, see this test's own module
    # comment) no longer happens, because the grace-period sleep gave
    # the newly-spawned process real time to overwrite its own row
    # first.
    assert len(crash_events) == 1
    assert len(restart_events) == 1
    assert result.stopped_cleanly is True
    assert result.restarts_used == 1


# --- Checkpoint 90: the orphaned-process race, found live during
# `LIVE-PAPER-2`.
#
# `start_worker()` unconditionally reassigns the supervisor's own
# `child_process` handle on every restart - before this checkpoint's fix,
# NOTHING confirmed the PREVIOUS process had genuinely exited at the OS
# level first. During a fast crash-restart burst (LIVE-PAPER-2 observed
# crashes ~22s apart), a prior process can still be mid-shutdown
# (`health_tracker.persist()` writes its own terminal state near the END
# of its shutdown sequence, but real wall-clock work - flushing, closing
# DB connections, unwinding the call stack - still follows that write
# before the OS process truly exits) when the next one is spawned. The
# orphan keeps polling `watch_for_stop_request()` independently and
# keeps writing its own periodic heartbeat to the SAME shared
# `WorkerRuntimeStatus` row, masking whatever the newly-tracked process
# writes - confirmed live: a genuine, correct `STOPPED` write was
# repeatedly overwritten back to a stale `RUNNING` by an orphan
# (`LIVE_PAPER-2_SUMMARY.md`).
def test_orphaned_process_race_is_prevented_by_confirming_exit_before_restart() -> None:
    """Simulates a slow-to-exit crashed process (worker_state=FAILED is
    observed immediately, but the real OS-level exit - here,
    `wait_for_worker_exit()` - only resolves some simulated time later,
    exactly like the real `flush_remainder()`/`close_old_connections()`
    tail every real crash shutdown goes through) across a fast
    crash-restart burst. Proves the fix: `start_worker()` for restart N+1
    is never called before `wait_for_worker_exit()` for restart N has
    been awaited and returned - the previous process is always confirmed
    gone before its replacement is spawned, so at most one process is
    ever alive/writing to `WorkerRuntimeStatus` at a time."""
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
    session_end = start + dt.timedelta(hours=6)
    clock_state = {"now": start}

    def now() -> dt.datetime:
        return clock_state["now"]

    # `event_order` records the exact interleaving of starts and
    # confirmed exits - the one thing this test actually proves.
    event_order: list[str] = []
    starts: list[int] = []
    # Tracks, for each started process (by its 1-based start index),
    # whether `wait_for_worker_exit()` has genuinely been awaited for it
    # yet - the crux of the fix under test.
    exited: dict[int, bool] = {}

    async def start_worker() -> None:
        idx = len(starts) + 1
        # THE invariant this test exists to prove: no new process may
        # start while the immediately-previous one has not yet been
        # confirmed exited.
        if idx > 1:
            assert exited.get(idx - 1) is True, (
                f"start_worker() for process #{idx} was called before process "
                f"#{idx - 1}'s exit was confirmed - the orphaned-process race "
                "this checkpoint fixes would reproduce here."
            )
        starts.append(idx)
        event_order.append(f"start:{idx}")
        exited[idx] = False
        # Every process here immediately fails - a pathologically fast
        # crash-restart burst, matching LIVE-PAPER-2's own ~22s-apart
        # observed cadence far more tightly than real wall-clock passing
        # through this fake's own `sleep()` below.
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

    async def is_worker_alive() -> bool:
        return True

    async def request_session_end_stop() -> None:
        await sync_to_async(repo.save)(
            provider,
            worker_state="STOPPED",
            token_state="VALID",
            watchdog_state="DISCONNECTED",
            last_packet_at=now(),
            last_bar_at=None,
            reconnect_count=0,
            consecutive_failures=0,
            subscribed_instrument_count=0,
            last_error_safe="",
        )

    async def wait_for_worker_exit() -> None:
        # Simulates the real, nonzero shutdown tail (flush/close/unwind)
        # that follows the FAILED write - genuine simulated time passes
        # here, exactly like the real `child_process.wait()` would take
        # for a still-exiting process, proving this isn't a no-op stub.
        idx = len(starts)
        if idx >= 1 and not exited.get(idx, True):
            clock_state["now"] = clock_state["now"] + dt.timedelta(seconds=0.5)
            exited[idx] = True
            event_order.append(f"exit_confirmed:{idx}")

    async def refresh_archive() -> None:
        return None

    poll_count = {"n": 0}

    async def sleep(seconds: float) -> None:
        poll_count["n"] += 1
        clock_state["now"] = clock_state["now"] + dt.timedelta(seconds=seconds)
        if poll_count["n"] >= 20:
            # Defensive cutoff so a regression can't hang the test suite.
            clock_state["now"] = session_end + dt.timedelta(seconds=1)

    result = __import__("asyncio").run(
        supervise_market_data_worker(
            provider=provider,
            max_restarts=4,
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

    # The burst crashes every single restart, 4 times over, exhausting
    # the bound - proving the fix holds across a genuinely fast,
    # repeated crash cycle, not just a single isolated one.
    assert result.max_restarts_exhausted is True
    assert result.restarts_used == 4
    assert len(starts) == 5  # initial start + 4 restarts

    # THE fix proof, on the actual recorded interleaving: every start
    # (after the first) is immediately preceded by that same index's own
    # exit confirmation - never two starts back-to-back with no
    # confirmed exit between them.
    assert event_order == [
        "start:1",
        "exit_confirmed:1",
        "start:2",
        "exit_confirmed:2",
        "start:3",
        "exit_confirmed:3",
        "start:4",
        "exit_confirmed:4",
        "start:5",
    ]
    # Every started process was confirmed exited except the very last
    # one (still "alive" when max_restarts_exhausted stops the loop
    # without a further wait - correct, since nothing restarts it).
    assert exited == {1: True, 2: True, 3: True, 4: True, 5: False}
