# File: src/intraday/infrastructure/market_data_providers/dhan/fake_tcp_server.py
#
# Checkpoint 56: a REAL local TCP server - `asyncio.start_server()`
# bound to `127.0.0.1` on an OS-assigned free port, accepting a real
# socket connection and writing a scripted sequence of real Dhan
# packet bytes onto it. This is the first genuinely socket-based test
# infrastructure in this project's Dhan integration - a real step past
# Checkpoint 55's purely in-memory `run_worker_session()`, which never
# touched a socket at all.
#
# HONEST, NAMED LIMITATION (do not let this be mistaken for more than
# it is): this is a raw TCP byte stream, NOT a WebSocket server - it
# does not perform the WebSocket opening handshake (HTTP Upgrade,
# Sec-WebSocket-Accept, frame masking) real Dhan's `wss://` endpoint
# requires. Implementing genuine WebSocket framing would mean adding a
# new third-party dependency (no `websockets`-equivalent package exists
# in this project today) or hand-rolling RFC 6455 framing - a bigger,
# separate decision this checkpoint does not make. What THIS module
# proves, honestly and completely: a real async client, reading from a
# real socket, using `stream_framing.py`'s real byte-counting logic,
# correctly reconstructs Dhan's own documented packet boundaries from
# a live byte stream - the exact framing problem a real WebSocket
# transport would also have to solve once past its own handshake.
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class FakeDhanTcpServer:
    """Sends `scripted_packets` (each already a complete, valid-shaped
    packet - header + body, as `packet_decoder.py`'s own byte-fixture
    helpers build) to the FIRST client that connects, in order, then
    closes the connection. One connection per server instance -
    deliberately minimal, matching this checkpoint's scoped ask (prove
    real socket I/O + real framing work, not build a fully general
    multi-client test server)."""

    scripted_packets: tuple[bytes, ...]
    host: str = "127.0.0.1"
    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    _port: int = field(default=0, init=False, repr=False)
    _connection_count: int = field(default=0, init=False, repr=False)

    @property
    def port(self) -> int:
        """`0` before `start()` - a caller must not read this until the
        server has actually bound a real socket and been assigned a
        real OS port."""
        return self._port

    @property
    def connection_count(self) -> int:
        return self._connection_count

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, 0)
        # `getsockname()` on the first bound socket gives us the REAL
        # OS-assigned port - never guessed, never hard-coded, so
        # concurrent test runs can never collide on a fixed port.
        self._port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(
        self, _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connection_count += 1
        try:
            for packet_bytes in self.scripted_packets:
                writer.write(packet_bytes)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
