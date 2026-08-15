# tests/unit/infrastructure/market_data_providers/dhan/test_async_worker_websocket.py
#
# Checkpoint 61: proves `run_worker_against_websocket()` - reusing the
# EXACT SAME decode/convert/state-machine core as
# `run_worker_against_stream()` (Checkpoint 57), driven by a REAL
# WebSocket connection this time. This is the acceptance proof for
# Decision 215/216: a real RFC 6455 handshake, real framing, real
# packets, real canonical Quotes - end to end.
from __future__ import annotations

import asyncio
import struct

from intraday.domain.market_data.contracts import Quote
from intraday.infrastructure.market_data_providers.dhan.async_worker import (
    AsyncWorkerRunResult,
    run_worker_against_websocket,
)
from intraday.infrastructure.market_data_providers.dhan.fake_websocket_server import (
    FakeDhanWebSocketServer,
)
from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
    DhanWebSocketTransport,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

_HEADER_STRUCT = struct.Struct("<BHBi")
_SECURITY_MAP = {2885: "RELIANCE", 1333: "HDFCBANK"}


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int = 1735900800) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def test_worker_processes_real_packets_over_a_real_websocket_then_stops_cleanly() -> None:
    async def scenario() -> tuple[AsyncWorkerRunResult, list[Quote]]:
        packets = (
            _ticker_bytes(security_id=2885, ltp=2900.0),
            _ticker_bytes(security_id=1333, ltp=1650.0),
            _ticker_bytes(security_id=2885, ltp=2905.0),
        )
        server = FakeDhanWebSocketServer(scripted_packets=packets)
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                received: list[Quote] = []
                result = await run_worker_against_websocket(
                    transport, security_id_to_symbol=_SECURITY_MAP, on_quote=received.append
                )
                return result, received
            finally:
                await transport.close()
        finally:
            await server.stop()

    result, received = asyncio.run(scenario())

    assert result.final_state is WorkerState.STOPPED
    assert result.quotes_processed == 3
    assert result.decode_failures == 0
    assert len(received) == 3
    assert received[0].instrument_id == "NSE:RELIANCE"


def test_worker_over_websocket_survives_a_malformed_packet() -> None:
    async def scenario() -> AsyncWorkerRunResult:
        unsupported = _HEADER_STRUCT.pack(5, 4, 1, 1333) + b"\x00\x00\x00\x00"
        packets = (unsupported, _ticker_bytes(security_id=2885, ltp=2900.0))
        server = FakeDhanWebSocketServer(scripted_packets=packets)
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                return await run_worker_against_websocket(
                    transport, security_id_to_symbol=_SECURITY_MAP
                )
            finally:
                await transport.close()
        finally:
            await server.stop()

    result = asyncio.run(scenario())

    assert result.decode_failures == 1
    assert result.quotes_processed == 1
    assert result.final_state is WorkerState.STOPPED


def test_worker_over_websocket_handles_a_disconnect_packet() -> None:
    async def scenario() -> AsyncWorkerRunResult:
        body = struct.pack("<h", 805)
        disconnect_bytes = _HEADER_STRUCT.pack(50, len(body), 1, 0) + body
        packets = (_ticker_bytes(security_id=2885, ltp=2900.0), disconnect_bytes)
        server = FakeDhanWebSocketServer(scripted_packets=packets)
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                return await run_worker_against_websocket(
                    transport, security_id_to_symbol=_SECURITY_MAP
                )
            finally:
                await transport.close()
        finally:
            await server.stop()

    result = asyncio.run(scenario())

    assert result.final_state is WorkerState.RECONNECTING
    assert result.quotes_processed == 1
