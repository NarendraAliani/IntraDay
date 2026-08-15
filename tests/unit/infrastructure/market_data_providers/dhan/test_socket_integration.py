# tests/unit/infrastructure/market_data_providers/dhan/test_socket_integration.py
#
# Checkpoint 56: the first genuinely socket-based integration test in
# this project's Dhan work - a REAL local TCP server
# (`FakeDhanTcpServer`), a REAL asyncio client connection, and REAL
# byte-stream framing (`read_one_packet_from_stream`) reconstructing
# Dhan's own packet boundaries from a live socket, decoded with the
# SAME `decode_packet()` Checkpoint 53 already proved correct against
# in-memory bytes. No `websockets`/third-party dependency - stdlib
# `asyncio` only, run via `asyncio.run()` inside ordinary sync test
# functions (no `pytest-asyncio` dependency needed for this).
#
# HONEST LABEL, repeated deliberately (see `fake_tcp_server.py`'s own
# module docstring): this is RAW TCP, not a WebSocket handshake/frame
# implementation. It proves real socket I/O and real framing, not a
# WebSocket-protocol-compliant server.
from __future__ import annotations

import asyncio
import struct

import pytest

from intraday.infrastructure.market_data_providers.dhan.fake_tcp_server import FakeDhanTcpServer
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanTickerPacket,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.stream_framing import (
    read_one_packet_from_stream,
)

_HEADER_STRUCT = struct.Struct("<BHBi")


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int = 1735900800) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER_STRUCT.pack(2, len(body), 1, security_id) + body


def test_a_real_client_reads_three_real_packets_off_a_real_socket() -> None:
    async def scenario() -> list[bytes]:
        packets = (
            _ticker_bytes(security_id=2885, ltp=2900.0),
            _ticker_bytes(security_id=1333, ltp=1650.0),
            _ticker_bytes(security_id=11536, ltp=3900.0),
        )
        server = FakeDhanTcpServer(scripted_packets=packets)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            received: list[bytes] = []
            try:
                while True:
                    raw = await read_one_packet_from_stream(reader)
                    if raw is None:
                        break
                    received.append(raw)
            finally:
                writer.close()
                await writer.wait_closed()
            return received
        finally:
            await server.stop()

    received = asyncio.run(scenario())

    assert len(received) == 3
    decoded = [decode_packet(raw) for raw in received]
    assert all(isinstance(packet, DhanTickerPacket) for packet in decoded)
    assert [p.header.security_id for p in decoded] == [2885, 1333, 11536]  # type: ignore[union-attr]
    assert abs(decoded[0].last_traded_price - 2900.0) < 0.01  # type: ignore[union-attr]


def test_a_real_client_correctly_sees_clean_end_of_stream() -> None:
    async def scenario() -> bytes | None:
        server = FakeDhanTcpServer(scripted_packets=(_ticker_bytes(security_id=2885, ltp=100.0),))
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                first = await read_one_packet_from_stream(reader)
                assert first is not None
                # The server only scripted ONE packet - the next read
                # must observe a clean end-of-stream, never an error.
                return await read_one_packet_from_stream(reader)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    second_read = asyncio.run(scenario())

    assert second_read is None


def test_a_genuinely_truncated_stream_raises_never_silently_returns_none() -> None:
    """A peer that closes mid-header (fewer than 8 bytes ever arrive)
    is a DIFFERENT, genuinely abnormal condition from a clean close -
    the framing reader must not conflate the two."""

    async def scenario() -> None:
        async def handle(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(b"\x02\x00\x01")  # 3 bytes - far short of an 8-byte header
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                with pytest.raises(asyncio.IncompleteReadError):
                    await read_one_packet_from_stream(reader)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_server_port_is_real_and_nonzero_only_after_start() -> None:
    async def scenario() -> tuple[int, int]:
        server = FakeDhanTcpServer(scripted_packets=())
        before = server.port
        await server.start()
        try:
            after = server.port
            return before, after
        finally:
            await server.stop()

    before, after = asyncio.run(scenario())

    assert before == 0
    assert after != 0


def test_server_tracks_connection_count() -> None:
    async def scenario() -> int:
        server = FakeDhanTcpServer(scripted_packets=(_ticker_bytes(security_id=2885, ltp=100.0),))
        await server.start()
        try:
            reader, writer = await asyncio.open_connection(server.host, server.port)
            try:
                await read_one_packet_from_stream(reader)
            finally:
                writer.close()
                await writer.wait_closed()
            return server.connection_count
        finally:
            await server.stop()

    count = asyncio.run(scenario())

    assert count == 1
