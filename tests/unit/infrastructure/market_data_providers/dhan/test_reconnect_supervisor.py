# tests/unit/infrastructure/market_data_providers/dhan/test_reconnect_supervisor.py
#
# Checkpoint 64.1: unit coverage for the reconnect-with-backoff
# supervisor. `sleep` is always a fake, instant no-op that just
# RECORDS the requested delay - this file never actually waits, and
# never opens a real or fake socket; `connect_and_run` is a plain
# Python callable returning pre-scripted `AsyncWorkerRunResult`s. Uses
# plain `asyncio.run()` inside ordinary sync test functions, matching
# this project's own established convention (no `pytest-asyncio`
# dependency - see `test_async_worker_websocket.py`).
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from intraday.infrastructure.market_data_providers.dhan.async_worker import AsyncWorkerRunResult
from intraday.infrastructure.market_data_providers.dhan.reconnect_supervisor import (
    ReconnectSupervisorResult,
    run_worker_with_reconnect,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState


def _fake_sleep_recorder() -> tuple[list[float], Callable[[float], Awaitable[None]]]:
    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, _sleep


def test_a_clean_stop_on_the_first_attempt_never_reconnects() -> None:
    calls = 0

    async def connect_and_run() -> AsyncWorkerRunResult:
        nonlocal calls
        calls += 1
        return AsyncWorkerRunResult(final_state=WorkerState.STOPPED, quotes_processed=3)

    result = asyncio.run(run_worker_with_reconnect(connect_and_run))

    assert calls == 1
    assert result.final_state is WorkerState.STOPPED
    assert result.reconnect_count == 0
    assert result.total_quotes_processed == 3


def test_a_lost_connection_reconnects_and_eventually_succeeds() -> None:
    delays, fake_sleep = _fake_sleep_recorder()
    attempts = [
        AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING, quotes_processed=1),
        AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING, quotes_processed=2),
        AsyncWorkerRunResult(final_state=WorkerState.STOPPED, quotes_processed=5),
    ]
    call_count = 0

    async def connect_and_run() -> AsyncWorkerRunResult:
        nonlocal call_count
        result = attempts[call_count]
        call_count += 1
        return result

    async def scenario() -> ReconnectSupervisorResult:
        return await run_worker_with_reconnect(
            connect_and_run, sleep=fake_sleep, random_jitter=lambda: 0.5
        )

    result = asyncio.run(scenario())

    assert call_count == 3
    assert result.final_state is WorkerState.STOPPED
    assert result.reconnect_count == 2
    assert result.total_quotes_processed == 1 + 2 + 5
    assert len(delays) == 2  # one backoff sleep per reconnect, none after the final clean stop


def test_backoff_grows_exponentially_and_is_capped() -> None:
    delays, fake_sleep = _fake_sleep_recorder()

    async def connect_and_run() -> AsyncWorkerRunResult:
        return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)

    async def scenario() -> None:
        await run_worker_with_reconnect(
            connect_and_run,
            max_attempts=5,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=4.0,
            sleep=fake_sleep,
            random_jitter=lambda: 1.0,  # jitter factor 1.0 -> exactly the uncapped/capped value
        )

    asyncio.run(scenario())

    # 1, 2, 4, 4 (capped) - 4 sleeps for 5 attempts (last exhausts, no further sleep)
    assert delays == [1.0, 2.0, 4.0, 4.0]


def test_reconnect_attempts_are_bounded_never_infinite() -> None:
    delays, fake_sleep = _fake_sleep_recorder()
    call_count = 0

    async def connect_and_run() -> AsyncWorkerRunResult:
        nonlocal call_count
        call_count += 1
        return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)

    async def scenario() -> ReconnectSupervisorResult:
        return await run_worker_with_reconnect(
            connect_and_run, max_attempts=3, sleep=fake_sleep, random_jitter=lambda: 0.5
        )

    result = asyncio.run(scenario())

    assert call_count == 3  # never more than max_attempts
    assert result.final_state is WorkerState.FAILED
    assert result.last_disconnect_reason == "reconnect_attempts_exhausted"


def test_an_unrecoverable_auth_failure_is_never_retried() -> None:
    """The real safety requirement: an expired/invalid token must not
    trigger a blind retry loop that just repeats the same failure."""
    call_count = 0

    async def connect_and_run() -> AsyncWorkerRunResult:
        nonlocal call_count
        call_count += 1
        return AsyncWorkerRunResult(final_state=WorkerState.TOKEN_EXPIRED)

    result = asyncio.run(run_worker_with_reconnect(connect_and_run, max_attempts=5))

    assert call_count == 1  # never retried
    assert result.final_state is WorkerState.TOKEN_EXPIRED
    assert result.last_disconnect_reason == "unrecoverable:TOKEN_EXPIRED"


def test_a_stop_event_during_reconnect_stops_cleanly_without_further_attempts() -> None:
    delays, fake_sleep = _fake_sleep_recorder()
    call_count = 0

    async def scenario() -> ReconnectSupervisorResult:
        stop_event = asyncio.Event()

        async def connect_and_run() -> AsyncWorkerRunResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                stop_event.set()  # operator shuts down mid-reconnect
            return AsyncWorkerRunResult(final_state=WorkerState.RECONNECTING)

        return await run_worker_with_reconnect(
            connect_and_run, stop_event=stop_event, sleep=fake_sleep, random_jitter=lambda: 0.5
        )

    result = asyncio.run(scenario())

    assert call_count == 1
    assert result.final_state is WorkerState.STOPPED
    assert delays == []  # no backoff sleep - the stop was honored immediately
