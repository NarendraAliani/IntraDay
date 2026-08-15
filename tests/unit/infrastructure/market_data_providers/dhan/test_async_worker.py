# tests/unit/infrastructure/market_data_providers/dhan/test_async_worker.py
#
# Checkpoint 57: proves `run_worker_against_stream()` - the persistent
# packet-processing loop - correctly drives a REAL socket
# (`FakeDhanTcpServer`) continuously, not just once, reusing
# Checkpoint 56's real TCP infrastructure.
from __future__ import annotations

import asyncio
import struct

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    AsyncWorkerRunResult,
    run_worker_against_stream,
)
from intraday.infrastructure.market_data_providers.dhan.fake_tcp_server import FakeDhanTcpServer
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

_HEADER_STRUCT = struct.Struct("<BHBi")
_SECURITY_MAP = {2885: "RELIANCE", 1333: "HDFCBANK"}


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int = 1735900800) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def _disconnect_bytes(*, reason_code: int = 805) -> bytes:
    body = struct.pack("<h", reason_code)
    return _HEADER_STRUCT.pack(50, len(body), 1, 0) + body


def test_worker_processes_every_real_packet_off_a_real_socket_then_stops_cleanly() -> None:
    async def scenario() -> tuple[AsyncWorkerRunResult, list[Quote]]:
        packets = (
            _ticker_bytes(security_id=2885, ltp=2900.0),
            _ticker_bytes(security_id=1333, ltp=1650.0),
            _ticker_bytes(security_id=2885, ltp=2905.0),
        )
        server = FakeDhanTcpServer(scripted_packets=packets)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                received: list[Quote] = []
                result = await run_worker_against_stream(
                    reader,
                    security_id_to_symbol=_SECURITY_MAP,
                    on_quote=received.append,
                )
                return result, received
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    result, received = asyncio.run(scenario())

    assert result.final_state is WorkerState.STOPPED
    assert result.quotes_processed == 3
    assert result.decode_failures == 0
    assert result.rejected_packets == 0
    assert len(received) == 3
    assert received[0].instrument_id == "NSE:RELIANCE"


def test_worker_survives_a_malformed_packet_and_keeps_processing() -> None:
    async def scenario() -> AsyncWorkerRunResult:
        # A "malformed" packet here means a syntactically valid header
        # naming an unsupported feed-response code (still real,
        # correctly-framed bytes over the real socket).
        unsupported = _HEADER_STRUCT.pack(5, 4, 1, 1333) + b"\x00\x00\x00\x00"
        packets = (unsupported, _ticker_bytes(security_id=2885, ltp=2900.0))
        server = FakeDhanTcpServer(scripted_packets=packets)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                return await run_worker_against_stream(reader, security_id_to_symbol=_SECURITY_MAP)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    result = asyncio.run(scenario())

    assert result.decode_failures == 1
    assert result.quotes_processed == 1
    assert result.final_state is WorkerState.STOPPED


def test_a_disconnect_packet_over_the_real_socket_ends_the_loop_in_reconnecting() -> None:
    async def scenario() -> AsyncWorkerRunResult:
        packets = (_ticker_bytes(security_id=2885, ltp=2900.0), _disconnect_bytes())
        server = FakeDhanTcpServer(scripted_packets=packets)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                return await run_worker_against_stream(reader, security_id_to_symbol=_SECURITY_MAP)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    result = asyncio.run(scenario())

    assert result.final_state is WorkerState.RECONNECTING
    assert result.quotes_processed == 1


def test_stop_event_ends_the_loop_promptly_without_processing_more_packets() -> None:
    async def scenario() -> AsyncWorkerRunResult:
        packets = tuple(
            _ticker_bytes(security_id=2885, ltp=100.0 + i, ltt_epoch=1735900800 + i)
            for i in range(50)
        )
        server = FakeDhanTcpServer(scripted_packets=packets)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            stop_event = asyncio.Event()

            async def _stop_after_first(_quote: Quote) -> None:
                stop_event.set()

            try:
                return await run_worker_against_stream(
                    reader,
                    security_id_to_symbol=_SECURITY_MAP,
                    on_quote=_stop_after_first,
                    stop_event=stop_event,
                )
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    result = asyncio.run(scenario())

    assert result.final_state is WorkerState.STOPPED
    # Stopped promptly after the first packet set the event - nowhere
    # near all 50 scripted packets were processed.
    assert result.quotes_processed < 5
