# File: src/intraday/infrastructure/market_data_providers/dhan/stream_framing.py
#
# Checkpoint 56: reads ONE complete Dhan v2 packet off a real
# `asyncio.StreamReader` - the byte-framing logic a real socket-based
# transport needs that a purely in-memory decoder (Checkpoint 53) never
# had to solve: a TCP/WebSocket byte stream delivers bytes, not
# pre-chunked packets, so the reader must know exactly how many bytes
# make up "one packet" using the packet's OWN header
# (`message_length`, VERIFIED_PRIMARY - see
# docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md) -
# read the 8-byte header first, then read exactly `message_length` more
# bytes for the body.
#
# Pure stdlib `asyncio` - no new third-party dependency. Deliberately
# separate from `packet_decoder.py` (which stays synchronous and
# I/O-free) - this module's ONE job is turning a byte STREAM into
# discrete packet byte STRINGS; decoding those bytes into a typed
# packet remains `packet_decoder.decode_packet()`'s job, unchanged.
from __future__ import annotations

import asyncio

from intraday.infrastructure.market_data_providers.dhan.packet_decoder import HEADER_SIZE


async def read_one_packet_from_stream(reader: asyncio.StreamReader) -> bytes | None:
    """Reads exactly one complete Dhan packet (header + body) from
    `reader`. Returns `None` on a clean end-of-stream (the peer closed
    the connection with no partial data pending) - the caller's normal
    "the feed ended" signal, never an exception. Raises
    `asyncio.IncompleteReadError` only for a genuinely truncated stream
    (a peer that closes mid-packet) - a real, distinct failure a caller
    must be able to tell apart from a clean close; this module does
    not swallow that, since silently treating "peer died mid-packet"
    the same as "peer said goodbye cleanly" would hide a real
    connection problem from whatever layer is watching worker health."""
    try:
        header_bytes = await reader.readexactly(HEADER_SIZE)
    except asyncio.IncompleteReadError as exc:
        if exc.partial == b"":
            # A clean end-of-stream BEFORE any new packet started -
            # the normal "the feed ended" signal.
            return None
        # The peer closed mid-header - a genuinely truncated stream,
        # distinct from a clean close, deliberately NOT swallowed.
        raise

    # The header's own `message_length` field (bytes 1-2, little-endian
    # int16 - VERIFIED_PRIMARY) tells us exactly how many MORE bytes
    # belong to this packet's body - no separate framing protocol
    # needed beyond what Dhan's own packet shape already provides.
    message_length = int.from_bytes(header_bytes[1:3], byteorder="little", signed=False)
    body_bytes = await reader.readexactly(message_length) if message_length > 0 else b""
    return header_bytes + body_bytes
