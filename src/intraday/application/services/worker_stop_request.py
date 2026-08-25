# File: src/intraday/application/services/worker_stop_request.py
#
# Checkpoint 64.73 Phase 8: THE graceful-shutdown redesign.
#
# WHY NOT ANOTHER SIGNAL WORKAROUND. 64.72 made three genuine attempts
# to stop a running worker gracefully (CTRL_C_EVENT via console attach,
# plain `taskkill` without /F, and a repeat of the former) and all three
# failed for the same structural reason: the worker had been launched as
# a detached background process, so it was not console-attached in the
# way `GenerateConsoleCtrlEvent` requires, and Windows has no
# deliverable SIGTERM at all. The worker had to be force-terminated and
# `WorkerRuntimeStatus.worker_state` was left permanently lying at
# RUNNING. A fourth signal trick would have the same failure mode.
#
# THE MECHANISM INSTEAD: the worker already owns a `WorkerRuntimeStatus`
# row and already runs an async loop. So a stop request becomes a
# COLUMN on that row (`stop_requested_at`), written by a management
# command and polled by the watcher below, which sets the SAME
# `asyncio.Event` the signal handlers already set. This is:
#
#   * process-independent - no PID discovery, no console attachment, no
#     OS signal semantics, works identically for a background-launched
#     process;
#   * project-native - reuses the established "one row per provider,
#     written by whichever process knows, read by the other" pattern
#     (`ProviderConnectionStatus`, Checkpoint 22) rather than inventing
#     a control plane;
#   * NOT a network endpoint - the directive's explicit preference, and
#     unnecessary given a shared database already exists;
#   * deterministically testable - this module is pure asyncio over an
#     injected repository and injected sleep, so shutdown can be proven
#     with a fake repository and NO live Dhan connection at all.
#
# OS signal handlers are deliberately KEPT in the worker as a secondary
# path for the interactive-foreground case. This watcher is the primary,
# reliable one.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from intraday.application.repositories.worker_runtime_status import (
    WorkerStopRequest,
)

DEFAULT_POLL_SECONDS = 2.0
"""Fast enough that an operator sees the worker stop promptly, slow
enough that a whole trading session costs a trivial number of tiny
indexed single-row reads."""


async def watch_for_stop_request(
    stop_event: asyncio.Event,
    *,
    provider: str,
    get_stop_request: Callable[[], Awaitable[WorkerStopRequest | None]],
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    report: Callable[[str], object] | None = None,
) -> WorkerStopRequest | None:
    """Polls for a stop request until one arrives or `stop_event` is set
    by some other path (an OS signal that DID work, or the worker
    finishing on its own).

    Returns the request that caused the stop, or `None` if the watcher
    exited because the event was already set elsewhere - so a caller can
    report truthfully WHY the worker stopped rather than guessing.

    `get_stop_request` is injected as an async callable (rather than the
    repository directly) because the worker runs in an async context
    where Django ORM access must go through `sync_to_async` - keeping
    that bridge at the call site leaves this module free of any Django
    dependency, which is what makes it unit-testable in isolation."""
    while not stop_event.is_set():
        request = await get_stop_request()
        if request is not None:
            if report is not None:
                report(
                    f"  stop request observed for provider={provider!r} "
                    f"requested_by={request.requested_by!r} "
                    f"reason={request.reason_safe!r} - initiating graceful shutdown"
                )
            stop_event.set()
            return request
        await sleep(poll_seconds)
    return None


__all__ = ["DEFAULT_POLL_SECONDS", "watch_for_stop_request"]
