# File: src/intraday/infrastructure/market_data_providers/dhan/reconnect_supervisor.py
#
# Checkpoint 64.1: the reconnect-with-backoff loop `async_worker.py`'s
# own module docstrings named as explicitly NOT built - both
# `run_worker_against_stream()` and `run_worker_against_websocket()`
# process exactly ONE connection and return on disconnect; nothing
# reconnects. This module is that missing outer loop - deliberately
# transport-agnostic (it takes a caller-supplied `connect_and_run`
# coroutine factory, never a specific transport type), so it works
# identically whether the inner connection is the real Dhan WebSocket
# path, the local `--provider fake-ws` test path, or any future
# transport - never a second, transport-specific reconnect
# implementation.
#
# REQUIRED BEHAVIOR (Checkpoint 64.1's own brief): bounded exponential
# backoff with jitter, never an infinite tight reconnect loop; a
# terminal/unrecoverable worker state (AUTH_FAILED, TOKEN_EXPIRED,
# FAILED) is NEVER retried - reconnecting against an auth problem the
# worker itself already diagnosed would just repeat the same failure,
# burn Dhan's own rate limits, and mask the real problem (an expired/
# invalid credential, which needs a human, not a retry) behind
# misleading "still trying" activity.
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from intraday.infrastructure.market_data_providers.dhan.async_worker import AsyncWorkerRunResult
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

# Terminal, NEVER-retried states - see module docstring for why.
_UNRECOVERABLE_STATES = frozenset(
    {WorkerState.AUTH_FAILED, WorkerState.TOKEN_EXPIRED, WorkerState.FAILED}
)


@dataclass(slots=True)
class ReconnectSupervisorResult:
    final_state: WorkerState
    attempts: int = 0
    reconnect_count: int = 0
    total_quotes_processed: int = 0
    consecutive_failures: int = 0
    last_disconnect_reason: str | None = None
    connection_history: list[WorkerState] = field(default_factory=list)
    """One entry per connection attempt's own final state - the full
    incident record `_UNRECOVERABLE_STATES`-scale failures need, not
    just the last one."""


async def run_worker_with_reconnect(
    connect_and_run: Callable[[], Awaitable[AsyncWorkerRunResult]],
    *,
    max_attempts: int = 5,
    initial_backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 30.0,
    stop_event: asyncio.Event | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_jitter: Callable[[], float] = random.random,
) -> ReconnectSupervisorResult:
    """Repeatedly calls `connect_and_run()` (each call is expected to
    make one fresh connection attempt and process packets until either
    a clean stop or a disconnect) - reconnecting with bounded
    exponential backoff ONLY when the connection was genuinely LOST
    (`WorkerState.RECONNECTING`), never for a clean stop or an
    unrecoverable failure.

    Backoff formula: `min(initial * 2**(attempt-1), max) * (0.5 + jitter*0.5)`
    - full exponential growth capped at `max_backoff_seconds`, with
    jitter keeping the actual delay in the upper half of that window
    (never exactly 0, which would degrade to a tight loop) rather than
    a fixed schedule multiple concurrent workers could synchronize on.
    """
    result = ReconnectSupervisorResult(final_state=WorkerState.STOPPED)

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        run_result = await connect_and_run()
        result.total_quotes_processed += run_result.quotes_processed
        result.connection_history.append(run_result.final_state)

        if run_result.final_state is WorkerState.STOPPED:
            # A clean stop (stream ended on its own, or a stop was
            # requested) - the supervisor's job is done, no reconnect.
            result.final_state = WorkerState.STOPPED
            result.consecutive_failures = 0
            return result

        if run_result.final_state in _UNRECOVERABLE_STATES:
            result.final_state = run_result.final_state
            result.last_disconnect_reason = f"unrecoverable:{run_result.final_state.value}"
            return result

        if run_result.final_state is WorkerState.RECONNECTING:
            result.reconnect_count += 1
            result.consecutive_failures += 1
            result.last_disconnect_reason = "connection_lost"

            if stop_event is not None and stop_event.is_set():
                result.final_state = WorkerState.STOPPED
                return result

            if attempt >= max_attempts:
                result.final_state = WorkerState.FAILED
                result.last_disconnect_reason = "reconnect_attempts_exhausted"
                return result

            backoff = min(initial_backoff_seconds * (2 ** (attempt - 1)), max_backoff_seconds)
            delay = backoff * (0.5 + random_jitter() * 0.5)
            await sleep(delay)
            continue

        # Any other final state (e.g. the connection never reached
        # RUNNING at all) - not a state this supervisor knows how to
        # retry meaningfully; report it honestly rather than guessing.
        result.final_state = run_result.final_state
        return result

    result.final_state = WorkerState.FAILED
    result.last_disconnect_reason = "reconnect_attempts_exhausted"
    return result


__all__ = ["ReconnectSupervisorResult", "run_worker_with_reconnect"]
