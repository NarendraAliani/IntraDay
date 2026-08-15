# File: src/intraday/infrastructure/market_data_providers/dhan/packet_decoder.py
#
# Checkpoint 53: a dedicated binary-packet decoder for the DhanHQ v2
# Live Market Feed WebSocket - built against VERIFIED_PRIMARY facts
# from Dhan's own official documentation, fetched fresh this checkpoint
# (see docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md
# for the full research trail and every field's exact byte layout).
#
# Deliberately SEPARATE from transport (no socket/connection code here)
# and from domain conversion (no `Quote`/`Bar` construction here) -
# this module's ONE job is: raw bytes in, a typed, safe-to-inspect
# packet (or an explicit decode failure) out. Never raises on malformed
# input - a single corrupt/truncated packet on a live feed must never
# be able to crash the persistent worker that would eventually consume
# this decoder's output (Checkpoint 53's own explicit "no malformed
# packet may crash the entire worker" requirement).
#
# HONEST SCOPE LIMIT: Checkpoint 54 adds the Quote packet (code 4) to
# Checkpoint 53's original Ticker (code 2) and Disconnect (code 50).
# OI/PrevClose/Full remain documented (see the research doc) but NOT
# implemented - extending to them is mechanical once this architecture
# is proven correct against three real shapes, not attempted here to
# avoid spreading effort thin across all seven packet types.
from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum

# All Dhan v2 WebSocket packets share this 8-byte header
# (VERIFIED_PRIMARY, see research doc): byte 0 = feed response code,
# bytes 1-2 = message length (payload, little-endian int16), byte 3 =
# exchange segment code, bytes 4-7 = security ID (little-endian int32).
HEADER_SIZE = 8
"""Public re-export of the header size - `stream_framing.py` (Checkpoint
56) needs this to know how many bytes to read off a real socket before
it can even see the `message_length` field that tells it how much more
to read for the body. Every OTHER reference in this module still uses
the module-local alias below to keep existing code unchanged."""
_HEADER_SIZE = HEADER_SIZE
_HEADER_STRUCT = struct.Struct("<BHBi")  # < = little-endian (VERIFIED_PRIMARY)

# Ticker packet (code 2): header + float32 LTP + int32 LTT (epoch seconds).
_TICKER_BODY_STRUCT = struct.Struct("<fi")
_TICKER_PACKET_SIZE = _HEADER_SIZE + _TICKER_BODY_STRUCT.size

# Quote packet (code 4, VERIFIED_PRIMARY - see research doc): header +
# float32 LTP + int16 LTQ + int32 LTT (epoch) + float32 ATP + int32
# volume + int32 total sell qty + int32 total buy qty + float32 open +
# float32 close + float32 high + float32 low, in exactly that order -
# format string built field-by-field against the documented byte
# ranges (f=float32, h=int16, i=int32), not assumed from a repeated
# pattern.
_QUOTE_BODY_STRUCT = struct.Struct("<fhifiiiffff")
_QUOTE_PACKET_SIZE = _HEADER_SIZE + _QUOTE_BODY_STRUCT.size

# Disconnect packet (code 50): header + int16 disconnect reason code.
_DISCONNECT_BODY_STRUCT = struct.Struct("<h")
_DISCONNECT_PACKET_SIZE = _HEADER_SIZE + _DISCONNECT_BODY_STRUCT.size


class DhanFeedResponseCode(IntEnum):
    """Only the codes this decoder actually acts on are named as
    members - every OTHER documented code (5/6/8/...) is still
    correctly recognized as UNSUPPORTED_PACKET_TYPE by
    `decode_packet()` below, never silently misinterpreted as one of
    these three."""

    TICKER = 2
    QUOTE = 4
    DISCONNECT = 50


class PacketDecodeFailureReason(IntEnum):
    TRUNCATED_HEADER = 1
    """Fewer than 8 bytes total - cannot even read the header."""
    UNSUPPORTED_PACKET_TYPE = 2
    """A syntactically valid header, but a feed response code this
    decoder does not implement this checkpoint (e.g. OI/PrevClose/Full)."""
    TRUNCATED_BODY = 3
    """The header parsed and named a supported packet type, but fewer
    bytes remain than that packet type's own documented body size."""


@dataclass(frozen=True, slots=True)
class DhanPacketHeader:
    feed_response_code: int
    message_length: int
    exchange_segment_code: int
    security_id: int


@dataclass(frozen=True, slots=True)
class DhanTickerPacket:
    header: DhanPacketHeader
    last_traded_price: float
    last_trade_time: datetime
    """Converted from the documented epoch-seconds int32 to a UTC
    `datetime` at decode time - never left as a bare int for a caller
    to misinterpret as local time or milliseconds."""


@dataclass(frozen=True, slots=True)
class DhanQuotePacket:
    header: DhanPacketHeader
    last_traded_price: float
    last_traded_quantity: int
    last_trade_time: datetime
    average_trade_price: float
    volume: int
    total_sell_quantity: int
    total_buy_quantity: int
    day_open: float
    day_close: float
    day_high: float
    day_low: float


@dataclass(frozen=True, slots=True)
class DhanDisconnectPacket:
    header: DhanPacketHeader
    disconnect_reason_code: int


@dataclass(frozen=True, slots=True)
class PacketDecodeFailure:
    reason: PacketDecodeFailureReason
    raw_length: int
    feed_response_code: int | None
    """`None` only when the failure is `TRUNCATED_HEADER` (too short to
    even read the code byte)."""


DecodedDhanPacket = DhanTickerPacket | DhanQuotePacket | DhanDisconnectPacket | PacketDecodeFailure


def decode_header(raw: bytes) -> DhanPacketHeader | None:
    """`None` if `raw` is too short to contain even the 8-byte header -
    the caller (`decode_packet()`) turns this into a
    `TRUNCATED_HEADER` failure; exposed separately since a future
    packet-type decoder only ever needs the header, never the whole
    `decode_packet()` dispatch."""
    if len(raw) < _HEADER_SIZE:
        return None
    code, length, segment, security_id = _HEADER_STRUCT.unpack(raw[:_HEADER_SIZE])
    return DhanPacketHeader(
        feed_response_code=code,
        message_length=length,
        exchange_segment_code=segment,
        security_id=security_id,
    )


def decode_packet(raw: bytes) -> DecodedDhanPacket:
    """The one dispatch entry point - NEVER raises. Every malformed,
    truncated, or unsupported input becomes a `PacketDecodeFailure`
    with a specific, inspectable reason, never an exception the caller
    would need to catch (or, worse, accidentally not catch)."""
    header = decode_header(raw)
    if header is None:
        return PacketDecodeFailure(
            reason=PacketDecodeFailureReason.TRUNCATED_HEADER,
            raw_length=len(raw),
            feed_response_code=None,
        )

    if header.feed_response_code == DhanFeedResponseCode.TICKER:
        if len(raw) < _TICKER_PACKET_SIZE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.TRUNCATED_BODY,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        ltp, ltt_epoch = _TICKER_BODY_STRUCT.unpack(raw[_HEADER_SIZE:_TICKER_PACKET_SIZE])
        return DhanTickerPacket(
            header=header,
            last_traded_price=ltp,
            last_trade_time=datetime.fromtimestamp(ltt_epoch, tz=UTC),
        )

    if header.feed_response_code == DhanFeedResponseCode.QUOTE:
        if len(raw) < _QUOTE_PACKET_SIZE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.TRUNCATED_BODY,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        (
            ltp,
            ltq,
            ltt_epoch,
            atp,
            volume,
            total_sell_qty,
            total_buy_qty,
            day_open,
            day_close,
            day_high,
            day_low,
        ) = _QUOTE_BODY_STRUCT.unpack(raw[_HEADER_SIZE:_QUOTE_PACKET_SIZE])
        return DhanQuotePacket(
            header=header,
            last_traded_price=ltp,
            last_traded_quantity=ltq,
            last_trade_time=datetime.fromtimestamp(ltt_epoch, tz=UTC),
            average_trade_price=atp,
            volume=volume,
            total_sell_quantity=total_sell_qty,
            total_buy_quantity=total_buy_qty,
            day_open=day_open,
            day_close=day_close,
            day_high=day_high,
            day_low=day_low,
        )

    if header.feed_response_code == DhanFeedResponseCode.DISCONNECT:
        if len(raw) < _DISCONNECT_PACKET_SIZE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.TRUNCATED_BODY,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        (reason_code,) = _DISCONNECT_BODY_STRUCT.unpack(raw[_HEADER_SIZE:_DISCONNECT_PACKET_SIZE])
        return DhanDisconnectPacket(header=header, disconnect_reason_code=reason_code)

    return PacketDecodeFailure(
        reason=PacketDecodeFailureReason.UNSUPPORTED_PACKET_TYPE,
        raw_length=len(raw),
        feed_response_code=header.feed_response_code,
    )
