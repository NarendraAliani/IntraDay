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
import contextlib
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from websockets.exceptions import ConnectionClosedError

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanDisconnectPacket,
    DhanFeedResponseCode,
    DhanOpenInterestPacket,
    PacketDecodeFailure,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    convert_packet_to_quote,
)
from intraday.infrastructure.market_data_providers.dhan.stream_framing import (
    read_one_packet_from_stream,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_diagnostics import (
    TimestampDiagnosticCollector,
    make_timestamp_diagnostic_sample,
)
from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
    DhanWebSocketTransport,
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
    last_close_code: int | None = None
    """Checkpoint 64.23: the RFC 6455 close code observed when the
    WebSocket path (`run_worker_against_websocket()` only - the raw-TCP
    path has no WebSocket close frame) ended via a `ConnectionClosedError`
    - `None` for a clean end-of-stream or when running against the raw
    TCP transport. Read from `DhanWebSocketTransport.close_code`, which
    contains no credential - safe to persist/log directly. This is the
    ONE piece of diagnostic detail this project's actual live connection
    attempt (Checkpoint 64.23) was missing: `reason="connection_lost"`
    alone could not distinguish a normal reconnect-worthy drop from a
    `1006` abnormal closure with zero data ever received."""


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

        if isinstance(decoded, DhanOpenInterestPacket):
            # Checkpoint 64.78: OI packets (feed response code 5) are now
            # DECODED rather than classified UNSUPPORTED_PACKET_TYPE. They
            # are not equity quotes and must never enter the equity path,
            # which subscribes NSE_EQ only (a cash instrument has no open
            # interest). Skipped explicitly, and NOT counted as a decode
            # failure - the packet decoded perfectly, it simply does not
            # belong to this consumer. Option OI routing lives in
            # `packet_to_option_observation.py`.
            continue

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


async def run_worker_against_websocket(
    transport: DhanWebSocketTransport,
    *,
    security_id_to_symbol: dict[int, str],
    on_quote: QuoteCallback | None = None,
    timestamp_diagnostics: TimestampDiagnosticCollector | None = None,
    stop_event: asyncio.Event | None = None,
) -> AsyncWorkerRunResult:
    """Checkpoint 61: the REAL-WebSocket sibling of
    `run_worker_against_stream()` - reuses the EXACT SAME decode
    (`decode_packet`) / conversion (`convert_packet_to_quote`) / state-
    machine (`apply_event`) logic, never reimplemented, only the
    packet SOURCE differs (`transport.receive_packets()`'s async
    iteration of already-framed WebSocket messages, instead of manual
    header-then-body byte counting off a raw TCP stream). This is the
    concrete proof that `async_worker.py`'s packet-processing core was
    genuinely transport-agnostic, as it was designed to be (Checkpoint
    57's own module docstring) - no rewrite was needed to add a second
    real transport, only a second thin loop around the same core
    logic.

    `transport` must already be connected (`await transport.connect()`)
    before this function is called - matches
    `run_worker_against_stream()`'s own "assumes the transport is
    already past its handshake" scope note exactly.

    Checkpoint 64.71 adds `stop_event`, bringing this function to
    parity with `run_worker_against_stream()`, which has accepted one
    since Checkpoint 57. Its absence here is precisely why Checkpoint
    64.70's real `--provider dhan` session had to be killed with
    `taskkill /T /F`: there was no way to ask a live WebSocket worker
    to stop.

    A `stop_event` cannot simply be polled between packets on this
    path. `receive_packets()` awaits the NEXT message, so on a quiet
    feed (outside market hours, or a thin instrument) that await can
    block far longer than a stop request should ever wait - polling
    would honor a stop only when the next tick happened to arrive.
    Instead a small watcher task awaits the event and CLOSES the
    transport, which ends the async iteration promptly and, on a real
    connection, sends a proper RFC 6455 close frame rather than
    dropping the socket. The watcher is always cancelled and awaited
    in `finally`, so no orphan task can outlive this call."""
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

    async def _close_transport_on_stop(event: asyncio.Event) -> None:
        await event.wait()
        await transport.close()

    watcher: asyncio.Task[None] | None = None
    if stop_event is not None:
        if stop_event.is_set():
            # Already asked to stop before the first packet was ever
            # read - honor it immediately rather than opening an
            # iteration we would only have to tear straight back down.
            transition(WorkerEvent.STOP_REQUESTED)
            transition(WorkerEvent.STOPPED_CLEANLY)
            result.final_state = state
            return result
        watcher = asyncio.create_task(_close_transport_on_stop(stop_event))

    try:
        async for raw in transport.receive_packets():
            if stop_event is not None and stop_event.is_set():
                break
            decoded = decode_packet(raw)
            if isinstance(decoded, PacketDecodeFailure):
                result.decode_failures += 1
                continue
            if isinstance(decoded, DhanDisconnectPacket):
                result.reconnect_relevant_disconnects += 1
                transition(WorkerEvent.CONNECTION_LOST)
                break

            if isinstance(decoded, DhanOpenInterestPacket):
                # Checkpoint 64.78: OI packets (feed response code 5) are now
                # DECODED rather than classified UNSUPPORTED_PACKET_TYPE. They
                # are not equity quotes and must never enter the equity path,
                # which subscribes NSE_EQ only (a cash instrument has no open
                # interest). Skipped explicitly, and NOT counted as a decode
                # failure - the packet decoded perfectly, it simply does not
                # belong to this consumer. Option OI routing lives in
                # `packet_to_option_observation.py`.
                continue

            conversion = convert_packet_to_quote(
                decoded, security_id_to_symbol=security_id_to_symbol
            )
            if not conversion.accepted:
                result.rejected_packets += 1
                continue
            assert conversion.quote is not None
            result.quotes_processed += 1
            if timestamp_diagnostics is not None and timestamp_diagnostics.enabled:
                # Checkpoint 64.70: THE first real wiring of the
                # Checkpoint 64.64-prepared collector - explicit opt-in
                # only (caller passes an already-`enabled=True`
                # collector), a no-op otherwise. `packet_type` comes
                # straight from the decoded header's own feed response
                # code (never guessed), `fetched_at_utc` is captured
                # HERE, immediately on receipt, before any DB/aggregation
                # work that could add its own latency to the measurement.
                try:
                    packet_type = DhanFeedResponseCode(decoded.header.feed_response_code).name
                except ValueError:
                    packet_type = f"UNKNOWN_{decoded.header.feed_response_code}"
                timestamp_diagnostics.record(
                    make_timestamp_diagnostic_sample(
                        symbol=security_id_to_symbol.get(
                            decoded.header.security_id, str(decoded.header.security_id)
                        ),
                        packet_type=packet_type,
                        source_timestamp_utc=conversion.quote.timestamp,
                        fetched_at_utc=dt.datetime.now(tz=dt.UTC),
                    )
                )
            if on_quote is not None:
                callback_result = on_quote(conversion.quote)
                if callback_result is not None:
                    await callback_result
        else:
            # The async generator finished on its own - the peer
            # closed the WebSocket connection normally (a clean
            # end-of-stream, the WebSocket-path equivalent of
            # `read_one_packet_from_stream()` returning `None`).
            transition(WorkerEvent.STOP_REQUESTED)
            transition(WorkerEvent.STOPPED_CLEANLY)
    except ConnectionClosedError:
        if stop_event is not None and stop_event.is_set():
            # Checkpoint 64.71: the close we are observing is the one
            # our OWN watcher task just performed because a stop was
            # requested. That is a clean, intentional shutdown - it
            # must NOT be counted as a reconnect-relevant disconnect,
            # or the supervisor would dutifully reconnect to a worker
            # the operator just asked to stop.
            transition(WorkerEvent.STOP_REQUESTED)
            transition(WorkerEvent.STOPPED_CLEANLY)
        else:
            # An ABNORMAL close (the real `websockets` library's own
            # signal for this, distinct from a clean close) - treated
            # the same as a Disconnect packet on the raw-TCP path: a
            # connection problem the worker's own state machine must
            # know about, never silently swallowed.
            result.reconnect_relevant_disconnects += 1
            result.last_close_code = transport.close_code
            transition(WorkerEvent.CONNECTION_LOST)
    finally:
        if watcher is not None:
            watcher.cancel()
            # Awaiting the cancelled task is what actually guarantees
            # "no orphan remains" - `cancel()` alone only REQUESTS
            # cancellation and returns immediately.
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    if state is WorkerState.RUNNING and stop_event is not None and stop_event.is_set():
        # Left the loop via the in-loop stop check (`break`), which
        # bypasses the `else:` clean-stop branch - converge on the same
        # clean STOPPED outcome here so a stop reaches STOPPED by
        # whichever route it was noticed.
        transition(WorkerEvent.STOP_REQUESTED)
        transition(WorkerEvent.STOPPED_CLEANLY)

    result.final_state = state
    return result
