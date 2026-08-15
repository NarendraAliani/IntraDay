# File: src/intraday/infrastructure/market_data_providers/dhan/async_worker.py
#
# Checkpoint 57: the missing link Checkpoint 56 itself named - a real
# socket (`fake_tcp_server.py`) and real byte-stream framing
# (`stream_framing.py`) existed, but nothing looped them continuously
# against the worker state machine the way an actual persistent
# process would. `run_worker_against_stream()` is that loop: it reads
# packets off a REAL, already-open `asyncio.StreamReader` one at a
# time, forever (or until the stream ends / it is cancelled), applying
# the exact same decode -> state-transition -> Quote-conversion logic
# `worker_session.py`'s synchronous `run_worker_session()` already
# proved correct - reused, not reimplemented, for the packet-processing
# core; this module adds the ASYNC LOOP AROUND a live stream that
# synchronous function structurally cannot have (it only ever consumed
# a finite, already-known `Sequence`).
#
# HONEST SCOPE LIMIT, continuing the same discipline as every prior
# Dhan checkpoint in this project: this function assumes the transport
# is ALREADY connected and past its handshake - it does not itself
# perform TCP connect, WebSocket upgrade, or Dhan authentication/
# subscription. Those steps are applied as ASSUMED-SUCCESSFUL
# `WorkerEvent`s at the start of the loop for the SYNTHETIC provider
# this checkpoint's `manage.py` command uses (`fake_tcp_server.py` has
# no real auth/subscribe handshake to wait on) - a REAL Dhan transport
# would need to earn those transitions from genuine
# authenticate()/subscribe() calls, which remain unimplemented (no
# real WebSocket client exists in this project - see
# ACTIVE_PRODUCT_GAP_REGISTER.md for why, unchanged from Checkpoint 56).
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanDisconnectPacket,
    PacketDecodeFailure,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    convert_packet_to_quote,
)
from intraday.infrastructure.market_data_providers.dhan.stream_framing import (
    read_one_packet_from_stream,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import (
    WorkerEvent,
    WorkerState,
    apply_event,
)

QuoteCallback = Callable[[Quote], Awaitable[None] | None]
"""Called once per successfully converted `Quote`, synchronously or as
a coroutine - the caller (the `manage.py` command) decides what
"publish this quote" means; this module has no opinion (never persists
anything itself, matching every other infrastructure module in this
project that keeps I/O decisions at the composition-root boundary)."""


@dataclass(slots=True)
class AsyncWorkerRunResult:
    final_state: WorkerState
    quotes_processed: int = 0
    decode_failures: int = 0
    rejected_packets: int = 0
    reconnect_relevant_disconnects: int = 0


async def run_worker_against_stream(
    reader: asyncio.StreamReader,
    *,
    security_id_to_symbol: dict[int, str],
    on_quote: QuoteCallback | None = None,
    stop_event: asyncio.Event | None = None,
) -> AsyncWorkerRunResult:
    """The persistent packet-processing loop. Applies the ASSUMED-
    SUCCESSFUL startup sequence (`START_REQUESTED` ->
    `AUTH_SUCCEEDED` -> `CONNECTED` -> `SUBSCRIBED`, see module
    docstring's honest scope note), then reads and processes packets
    one at a time until EITHER the stream cleanly ends OR
    `stop_event` is set - whichever happens first, checked between
    each packet read so a stop request is honored promptly rather than
    only after the whole stream drains."""
    state = WorkerState.STOPPED
    result = AsyncWorkerRunResult(final_state=state)

    def transition(event: WorkerEvent) -> None:
        nonlocal state
        outcome = apply_event(state, event)
        if outcome.accepted:
            state = outcome.new_state

    for startup_event in (
        WorkerEvent.START_REQUESTED,
        WorkerEvent.AUTH_SUCCEEDED,
        WorkerEvent.CONNECTED,
        WorkerEvent.SUBSCRIBED,
    ):
        transition(startup_event)

    while state is WorkerState.RUNNING:
        if stop_event is not None and stop_event.is_set():
            transition(WorkerEvent.STOP_REQUESTED)
            transition(WorkerEvent.STOPPED_CLEANLY)
            break

        raw = await read_one_packet_from_stream(reader)
        if raw is None:
            # Clean end-of-stream - the feed ended on its own, not
            # because anyone asked us to stop.
            transition(WorkerEvent.STOP_REQUESTED)
            transition(WorkerEvent.STOPPED_CLEANLY)
            break

        decoded = decode_packet(raw)
        if isinstance(decoded, PacketDecodeFailure):
            result.decode_failures += 1
            continue
        if isinstance(decoded, DhanDisconnectPacket):
            result.reconnect_relevant_disconnects += 1
            transition(WorkerEvent.CONNECTION_LOST)
            break  # this checkpoint's loop does not itself reconnect - see scope note

        conversion = convert_packet_to_quote(decoded, security_id_to_symbol=security_id_to_symbol)
        if not conversion.accepted:
            result.rejected_packets += 1
            continue
        assert conversion.quote is not None
        result.quotes_processed += 1
        if on_quote is not None:
            callback_result = on_quote(conversion.quote)
            if callback_result is not None:
                await callback_result

    result.final_state = state
    return result
