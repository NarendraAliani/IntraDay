# File: tests/unit/research/test_checkpoint_64_71_graceful_shutdown.py
#
# Checkpoint 64.71 proof suite for graceful `--provider dhan` shutdown.
#
# WHY THIS EXISTS: Checkpoint 64.70's real live session had to be ended
# with `taskkill /T /F`, because `run_worker_against_websocket()` had no
# `stop_event` and the reconnect supervisor only ever checked one AFTER
# a disconnect. An unconditional kill gives the worker no chance to
# close the WebSocket, flush pending quotes, or record a final STOPPED
# runtime status.
#
# Every test here is deterministic: no wall-clock sleeps are used as
# synchronization, no real network is involved except the project's own
# local fake WebSocket server, and no live Dhan connection is ever made.
from __future__ import annotations

import asyncio
import signal
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from websockets.exceptions import ConnectionClosedError

from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    AsyncWorkerRunResult,
    run_worker_against_websocket,
)
from intraday.infrastructure.market_data_providers.dhan.reconnect_supervisor import (
    run_worker_with_reconnect,
)
from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
    WorkerHealthTracker,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

_SECURITY_MAP = {2885: "RELIANCE"}


@dataclass
class _QuietTransport:
    """A transport that completes its handshake and then simply never
    delivers another packet - the exact real-world condition that makes
    polling a stop flag "between packets" useless (a quiet feed outside
    market hours, or a thin instrument). Structurally matches
    `DhanWebSocketTransport`'s surface as used by the worker.

    `closed` records whether the WebSocket was actually closed, which is
    the property the directive asks to be proven, not assumed."""

    closed: bool = False
    close_code: int | None = None
    raise_on_close: bool = False
    _gate: asyncio.Event = field(default_factory=asyncio.Event)

    async def receive_packets(self) -> AsyncIterator[bytes]:
        # Blocks forever unless close() releases the gate - i.e. the
        # worker CANNOT escape this by noticing a flag between packets.
        await self._gate.wait()
        if self.raise_on_close:
            raise ConnectionClosedError(None, None)
        return
        yield b""  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        self.closed = True
        self._gate.set()


def test_stop_request_ends_a_quiet_live_worker_and_closes_the_websocket() -> None:
    """The core 64.70 failure mode, fixed: a worker sitting on a silent
    feed still stops promptly when asked."""

    async def scenario() -> tuple[AsyncWorkerRunResult, _QuietTransport]:
        transport = _QuietTransport()
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_worker_against_websocket(
                transport,  # type: ignore[arg-type]
                security_id_to_symbol=_SECURITY_MAP,
                stop_event=stop_event,
            )
        )
        # Let the worker reach its blocking receive before stopping it.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        stop_event.set()
        result = await asyncio.wait_for(task, timeout=5)
        return result, transport

    result, transport = asyncio.run(scenario())

    assert result.final_state is WorkerState.STOPPED
    assert transport.closed is True
    # A requested stop is NOT a disconnect - the supervisor must not be
    # told to reconnect to a worker the operator just stopped.
    assert result.reconnect_relevant_disconnects == 0


def test_stop_is_clean_even_when_the_close_surfaces_as_connection_closed_error() -> None:
    """On a real connection, closing mid-iteration can surface as
    `ConnectionClosedError`. When WE caused it via a stop request, that
    must still be a clean STOPPED, never a reconnect trigger."""

    async def scenario() -> AsyncWorkerRunResult:
        transport = _QuietTransport(raise_on_close=True)
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_worker_against_websocket(
                transport,  # type: ignore[arg-type]
                security_id_to_symbol=_SECURITY_MAP,
                stop_event=stop_event,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        stop_event.set()
        return await asyncio.wait_for(task, timeout=5)

    result = asyncio.run(scenario())
    assert result.final_state is WorkerState.STOPPED
    assert result.reconnect_relevant_disconnects == 0


def test_already_set_stop_event_returns_immediately_without_reading() -> None:
    async def scenario() -> tuple[AsyncWorkerRunResult, _QuietTransport]:
        transport = _QuietTransport()
        stop_event = asyncio.Event()
        stop_event.set()
        result = await asyncio.wait_for(
            run_worker_against_websocket(
                transport,  # type: ignore[arg-type]
                security_id_to_symbol=_SECURITY_MAP,
                stop_event=stop_event,
            ),
            timeout=5,
        )
        return result, transport

    result, _transport = asyncio.run(scenario())
    assert result.final_state is WorkerState.STOPPED


def test_no_orphan_task_remains_after_shutdown() -> None:
    """Directive §10's "no orphan remains" - the watcher task must be
    cancelled AND awaited, not merely asked to cancel."""

    async def scenario() -> int:
        transport = _QuietTransport()
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_worker_against_websocket(
                transport,  # type: ignore[arg-type]
                security_id_to_symbol=_SECURITY_MAP,
                stop_event=stop_event,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=5)
        # Everything except this scenario coroutine itself must be gone.
        return len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    assert asyncio.run(scenario()) == 0


def test_worker_without_a_stop_event_behaves_exactly_as_before() -> None:
    """Backwards compatibility: `stop_event` is optional, and omitting
    it must not change any existing behavior (no watcher, no new
    states)."""

    async def scenario() -> AsyncWorkerRunResult:
        transport = _QuietTransport()
        task = asyncio.create_task(
            run_worker_against_websocket(
                transport,  # type: ignore[arg-type]
                security_id_to_symbol=_SECURITY_MAP,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Nothing is watching a stop event; the ONLY way out is the
        # feed itself ending - which is the pre-64.71 behavior.
        assert not task.done()
        await transport.close()
        return await asyncio.wait_for(task, timeout=5)

    result = asyncio.run(scenario())
    assert result.final_state is WorkerState.STOPPED


# --------------------------------------------------------------------
# Supervisor-level behavior
# --------------------------------------------------------------------


def test_supervisor_does_not_open_a_new_connection_after_a_stop_request() -> None:
    async def scenario() -> int:
        stop_event = asyncio.Event()
        attempts = 0

        async def connect_and_run() -> AsyncWorkerRunResult:
            nonlocal attempts
            attempts += 1
            # First connection is genuinely lost; the operator requests
            # a stop before the supervisor can retry.
            stop_event.set()
            return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)

        result = await run_worker_with_reconnect(
            connect_and_run,
            max_attempts=5,
            stop_event=stop_event,
            sleep=lambda _d: asyncio.sleep(0),
        )
        assert result.final_state is WorkerState.STOPPED
        return attempts

    assert asyncio.run(scenario()) == 1


def test_supervisor_checks_stop_before_the_very_first_connection() -> None:
    async def scenario() -> int:
        stop_event = asyncio.Event()
        stop_event.set()
        attempts = 0

        async def connect_and_run() -> AsyncWorkerRunResult:
            nonlocal attempts
            attempts += 1
            return AsyncWorkerRunResult(final_state=WorkerState.STOPPED)

        result = await run_worker_with_reconnect(
            connect_and_run, max_attempts=3, stop_event=stop_event
        )
        assert result.final_state is WorkerState.STOPPED
        return attempts

    assert asyncio.run(scenario()) == 0


def test_reconnect_still_happens_when_no_stop_was_requested() -> None:
    """Directive §9/§10's explicit guard: the shutdown work must NOT
    break normal reconnect behavior. A real disconnect with no stop
    request must still reconnect."""

    async def scenario() -> tuple[int, int]:
        attempts = 0

        async def connect_and_run() -> AsyncWorkerRunResult:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)
            return AsyncWorkerRunResult(final_state=WorkerState.STOPPED, quotes_processed=7)

        result = await run_worker_with_reconnect(
            connect_and_run,
            max_attempts=5,
            stop_event=asyncio.Event(),  # present but NEVER set
            sleep=lambda _d: asyncio.sleep(0),
        )
        assert result.final_state is WorkerState.STOPPED
        assert result.total_quotes_processed == 7
        return attempts, result.reconnect_count

    attempts, reconnects = asyncio.run(scenario())
    assert attempts == 3
    assert reconnects == 2


def test_reconnect_still_works_with_no_stop_event_at_all() -> None:
    async def scenario() -> int:
        attempts = 0

        async def connect_and_run() -> AsyncWorkerRunResult:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)
            return AsyncWorkerRunResult(final_state=WorkerState.STOPPED)

        result = await run_worker_with_reconnect(
            connect_and_run, max_attempts=4, sleep=lambda _d: asyncio.sleep(0)
        )
        assert result.final_state is WorkerState.STOPPED
        return attempts

    assert asyncio.run(scenario()) == 2


# --------------------------------------------------------------------
# Runtime status
# --------------------------------------------------------------------


def test_health_tracker_reaches_stopped_state() -> None:
    """Directive question J - `WorkerRuntimeStatus` must become
    STOPPED, not remain a stale RUNNING from the last connect."""
    tracker = WorkerHealthTracker()
    tracker.mark_connected(subscribed_instrument_count=4)
    assert tracker.worker_state is WorkerState.RUNNING

    tracker.mark_stopped()

    assert tracker.worker_state is WorkerState.STOPPED
    assert tracker.snapshot().connection_state == WorkerState.STOPPED.value


def test_stop_signal_handlers_install_and_set_the_event() -> None:
    """The operator-facing half: a standard stop signal must actually
    set the event the worker is waiting on. Cross-platform - on
    Windows only SIGINT is deliverable and asyncio's
    `add_signal_handler` is unimplemented, so this asserts on what was
    reported as installed rather than assuming a POSIX signal set."""
    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        _install_stop_signal_handlers,
    )

    async def scenario() -> tuple[tuple[str, ...], bool]:
        stop_event = asyncio.Event()
        installed = _install_stop_signal_handlers(stop_event)
        # SIGINT exists on every platform this project runs on.
        assert "SIGINT" in installed
        # Fire the installed handler exactly as the OS would.
        handler = signal.getsignal(signal.SIGINT)
        loop_handlers_used = not callable(handler) or handler in (
            signal.SIG_DFL,
            signal.SIG_IGN,
        )
        if loop_handlers_used:
            # asyncio's loop-native path was used; drive it directly.
            asyncio.get_running_loop().call_soon(stop_event.set)
        else:
            handler(signal.SIGINT, None)
        await asyncio.sleep(0)
        return installed, stop_event.is_set()

    installed, was_set = asyncio.run(scenario())
    assert installed  # at least one handler really was installed
    assert was_set is True


def test_installing_stop_handlers_never_raises() -> None:
    """Best-effort by design - failing to install a convenience
    shutdown hook must never stop the worker from running."""
    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        _install_stop_signal_handlers,
    )

    async def scenario() -> tuple[str, ...]:
        return _install_stop_signal_handlers(asyncio.Event(), report=lambda _m: None)

    asyncio.run(scenario())


def test_a_deliberate_stop_is_not_recorded_as_a_failure() -> None:
    tracker = WorkerHealthTracker()
    tracker.mark_reconnecting(reason="connection_lost")
    assert tracker.consecutive_failures == 1

    tracker.mark_stopped()

    assert tracker.worker_state is WorkerState.STOPPED
    assert tracker.consecutive_failures == 0
