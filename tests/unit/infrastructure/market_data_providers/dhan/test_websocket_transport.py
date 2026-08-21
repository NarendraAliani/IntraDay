# tests/unit/infrastructure/market_data_providers/dhan/test_websocket_transport.py
#
# Checkpoint 61: the FIRST tests in this repository exercising a REAL
# RFC 6455 WebSocket handshake and frame protocol - a real client
# (`DhanWebSocketTransport`, backed by `websockets`) connecting to a
# real local WebSocket server (`FakeDhanWebSocketServer`), both using
# the SAME `websockets` library (Decision 215/216) as a real Dhan
# connection eventually would. Distinct from `test_socket_integration.py`
# (Checkpoint 56), which deliberately tests RAW TCP, not WebSocket.
from __future__ import annotations

import asyncio
import struct

import pytest

from intraday.infrastructure.market_data_providers.dhan.fake_websocket_server import (
    FakeDhanWebSocketServer,
)
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanTickerPacket,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
    DhanWebSocketTransport,
    DhanWebSocketTransportError,
)

_HEADER_STRUCT = struct.Struct("<BHBi")


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int = 1735900800) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def test_a_real_websocket_handshake_completes_and_packets_are_received() -> None:
    async def scenario() -> list[bytes]:
        packets = (
            _ticker_bytes(security_id=2885, ltp=2900.0),
            _ticker_bytes(security_id=1333, ltp=1650.0),
        )
        server = FakeDhanWebSocketServer(scripted_packets=packets)
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                received = [raw async for raw in transport.receive_packets()]
                return received
            finally:
                await transport.close()
        finally:
            await server.stop()

    received = asyncio.run(scenario())

    assert len(received) == 2
    decoded = [decode_packet(raw) for raw in received]
    assert all(isinstance(p, DhanTickerPacket) for p in decoded)
    assert [p.header.security_id for p in decoded] == [2885, 1333]  # type: ignore[union-attr]


def test_connect_to_a_nonexistent_server_raises_a_typed_error() -> None:
    async def scenario() -> None:
        transport = DhanWebSocketTransport(uri="ws://127.0.0.1:1")  # nothing listens on port 1
        await transport.connect()

    with pytest.raises(DhanWebSocketTransportError):
        asyncio.run(scenario())


def test_receive_before_connect_raises_a_typed_error() -> None:
    async def scenario() -> None:
        transport = DhanWebSocketTransport(uri="ws://127.0.0.1:9")
        async for _ in transport.receive_packets():
            pass

    with pytest.raises(DhanWebSocketTransportError):
        asyncio.run(scenario())


def test_send_before_connect_raises_a_typed_error() -> None:
    async def scenario() -> None:
        transport = DhanWebSocketTransport(uri="ws://127.0.0.1:9")
        await transport.send_json_text('{"RequestCode": 12}')

    with pytest.raises(DhanWebSocketTransportError):
        asyncio.run(scenario())


def test_server_tracks_a_real_connection() -> None:
    async def scenario() -> int:
        server = FakeDhanWebSocketServer(scripted_packets=())
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                async for _ in transport.receive_packets():
                    pass
            finally:
                await transport.close()
            return server.connection_count
        finally:
            await server.stop()

    count = asyncio.run(scenario())

    assert count == 1


def test_malformed_uri_is_rejected_before_any_connection_attempt() -> None:
    async def scenario() -> None:
        transport = DhanWebSocketTransport(uri="not-a-valid-uri")
        await transport.connect()

    with pytest.raises(DhanWebSocketTransportError):
        asyncio.run(scenario())


def test_a_connect_failure_never_leaks_the_token_or_client_id() -> None:
    """Checkpoint 64.23: a real Dhan URI embeds the live access token
    and client ID directly in its query string. This connection never
    succeeds (nothing listens on port 1), so `connect()` raises -
    `DhanWebSocketTransportError`'s message MUST redact those values,
    since this message flows into `WorkerHealthTracker.last_error_safe`,
    a field this project persists and serves over its readiness API."""

    async def scenario() -> None:
        transport = DhanWebSocketTransport(
            uri="ws://127.0.0.1:1?version=2&token=super-secret-token&clientId=1000012345&authType=2"
        )
        await transport.connect()

    with pytest.raises(DhanWebSocketTransportError) as excinfo:
        asyncio.run(scenario())

    message = str(excinfo.value)
    assert "super-secret-token" not in message
    assert "1000012345" not in message
    assert "token=<redacted>" in message
    assert "clientId=<redacted>" in message


def test_close_code_is_none_before_any_connection() -> None:
    transport = DhanWebSocketTransport(uri="ws://127.0.0.1:9")
    assert transport.close_code is None
    assert transport.close_reason is None


def test_close_code_reflects_the_real_close_after_a_clean_disconnect() -> None:
    async def scenario() -> int | None:
        server = FakeDhanWebSocketServer(scripted_packets=())
        await server.start()
        try:
            transport = DhanWebSocketTransport(uri=server.uri)
            await transport.connect()
            try:
                async for _ in transport.receive_packets():
                    pass
            finally:
                pass
            return transport.close_code
        finally:
            await server.stop()

    code = asyncio.run(scenario())
    assert code == 1000  # a clean, normal close
