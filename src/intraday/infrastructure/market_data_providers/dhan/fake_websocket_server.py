# File: src/intraday/infrastructure/market_data_providers/dhan/fake_websocket_server.py
#
# Checkpoint 61: a REAL local WebSocket server (RFC 6455, via the
# `websockets` library, Decision 215) - replacing Checkpoint 56's raw-
# TCP `FakeDhanTcpServer` for the specific purpose of proving
# `DhanWebSocketTransport` against a genuine WebSocket handshake, not
# a hand-counted byte stream. `FakeDhanTcpServer` remains in the
# codebase (Checkpoint 56/57/58/59's tests still use it and still
# pass) - this is an ADDITIONAL real server, not a replacement, since
# downgrading proven raw-TCP tests to "real WebSocket only" would
# needlessly risk existing, already-passing coverage.
from __future__ import annotations

from dataclasses import dataclass, field

from websockets.asyncio.server import Server, ServerConnection, serve


@dataclass
class FakeDhanWebSocketServer:
    """Sends `scripted_packets` to the first client that completes a
    real WebSocket handshake and connects, then closes. Mirrors
    `FakeDhanTcpServer`'s own shape (Checkpoint 56) deliberately, so
    the two are easy to compare side-by-side in tests - the only
    material difference is that THIS server speaks real WebSocket, not
    raw TCP."""

    scripted_packets: tuple[bytes, ...]
    host: str = "127.0.0.1"
    _server: Server | None = field(default=None, init=False, repr=False)
    _port: int = field(default=0, init=False, repr=False)
    _connection_count: int = field(default=0, init=False, repr=False)

    @property
    def port(self) -> int:
        return self._port

    @property
    def uri(self) -> str:
        return f"ws://{self.host}:{self._port}"

    @property
    def connection_count(self) -> int:
        return self._connection_count

    async def start(self) -> None:
        self._server = await serve(self._handle_client, self.host, 0)
        self._port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, connection: ServerConnection) -> None:
        self._connection_count += 1
        for packet_bytes in self.scripted_packets:
            await connection.send(packet_bytes)
        await connection.close()
