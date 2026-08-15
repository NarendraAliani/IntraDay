# File: src/intraday/infrastructure/market_data_providers/dhan/websocket_transport.py
#
# Checkpoint 61: the FIRST real WebSocket transport in this project's
# Dhan integration - built against `websockets` (Decision 215,
# Checkpoint 60's own research-backed, primary-source-verified
# choice). Genuinely performs the RFC 6455 opening handshake and frame
# protocol (via the `websockets` library, not hand-rolled - the exact
# thing Checkpoint 56's raw-TCP `FakeDhanTcpServer` explicitly declined
# to implement). This is a real step past raw TCP: Dhan's own endpoint
# is `wss://api-feed.dhan.co` (Checkpoint 53's VERIFIED_PRIMARY
# research), which REQUIRES a genuine WebSocket handshake - raw TCP
# framing (Checkpoint 56/57) could never have connected to it at all.
#
# Deliberately thin: this module's only job is CONNECT/RECEIVE/SEND/
# CLOSE over a real WebSocket. It knows nothing about Dhan packet
# structure (that remains `packet_decoder.py`'s job, unchanged) or
# worker state (that remains `worker_state.py`'s job, unchanged) -
# matches this project's own established "transport is dumb, decoding
# and state are separate" discipline (Checkpoint 53's own module
# docstring).
#
# HONEST SCOPE LIMIT: this transport works against ANY WebSocket
# server (real Dhan or a local test server) - the SAME code path, per
# the user's own explicit "the production client and test transport
# must be the same code, never two separate implementations"
# instruction this checkpoint. It does NOT itself implement Dhan
# authentication query-parameter construction beyond accepting a
# caller-supplied URI (the caller is responsible for building
# `wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2`,
# Checkpoint 53's VERIFIED_PRIMARY URL shape) - this environment's Dhan
# credential remains unusable for a real connection attempt
# (Checkpoint 41, unchanged), so no real Dhan URI was ever constructed
# or tested against, only the local fake server.
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import websockets
from websockets.asyncio.client import ClientConnection, connect


class DhanWebSocketTransportError(Exception):
    """Raised when CONNECT itself fails (handshake refused, connection
    refused, DNS failure, etc.) - a caller-visible, typed failure,
    never a bare library exception leaking through this module's own
    boundary."""


@dataclass(slots=True)
class DhanWebSocketTransport:
    """A real WebSocket connection, opened via a genuine RFC 6455
    handshake. `uri` may point at Dhan's own production endpoint OR a
    local test server (`fake_websocket_server.py`, this checkpoint) -
    this class does not know or care which."""

    uri: str
    ping_interval: float = 20.0
    """Matches Dhan's OWN documented 10s server ping / 40s client
    timeout (Checkpoint 53's VERIFIED_PRIMARY research) loosely - the
    `websockets` library's own default is also 20s; kept explicit
    here, not left implicit, so a future tuning pass has one obvious
    place to change it."""
    ping_timeout: float = 20.0
    _connection: ClientConnection | None = None

    async def connect(self) -> None:
        try:
            self._connection = await connect(
                self.uri, ping_interval=self.ping_interval, ping_timeout=self.ping_timeout
            )
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            # `WebSocketException` is the library's own common base for
            # every protocol-level failure (invalid URI, invalid
            # handshake, etc.) - catching it here, rather than each
            # specific subclass, means this module never has to be
            # updated every time the library adds a new failure
            # subtype; `OSError` separately covers transport-level
            # failures (connection refused, DNS failure).
            raise DhanWebSocketTransportError(f"failed to connect to {self.uri}: {exc!r}") from exc

    async def send_json_text(self, payload: str) -> None:
        """Sends a text frame - Dhan's own subscription/disconnect
        REQUEST messages are documented as JSON (Checkpoint 53's
        research: `{"RequestCode": 15, ...}`), always sent as text,
        never binary - only the SERVER's response packets are binary."""
        if self._connection is None:
            raise DhanWebSocketTransportError("not connected - call connect() first")
        await self._connection.send(payload)

    async def receive_packets(self) -> AsyncIterator[bytes]:
        """Yields one complete binary message per Dhan packet - unlike
        the raw-TCP path (`stream_framing.py`, Checkpoint 56), a real
        WebSocket connection already delivers whole messages per
        `recv()`/async-iteration call; the manual header-then-body
        byte-counting `read_one_packet_from_stream()` needed for a raw
        TCP stream is NOT needed here, since `websockets` already
        performs that framing as part of the RFC 6455 protocol itself.
        Ends cleanly (the async generator simply finishes) when the
        peer closes normally; a genuinely abnormal close surfaces as a
        `websockets.exceptions.ConnectionClosedError` raised by the
        underlying library, deliberately NOT caught here - the caller
        (the worker loop) decides what an abnormal close means for its
        own state machine, exactly as it already decides for a
        Disconnect PACKET on the raw-TCP path."""
        if self._connection is None:
            raise DhanWebSocketTransportError("not connected - call connect() first")
        async for message in self._connection:
            if isinstance(message, bytes):
                yield message
            # A text message here would be a non-Dhan-protocol
            # message (Dhan's own responses are documented as binary,
            # Checkpoint 53) - silently ignored rather than raised,
            # since a control/keepalive text frame is plausible and
            # should not be treated as a decode failure.

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
