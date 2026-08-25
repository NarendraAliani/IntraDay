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
from datetime import datetime
from enum import IntEnum

from intraday.infrastructure.market_data_providers.dhan.timestamp_normalization import (
    normalize_dhan_websocket_timestamp,
)

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

# OI packet (code 5, VERIFIED at Checkpoint 64.76 against Dhan's own
# live-market-feed documentation): a 12-byte packet - the SAME 8-byte
# header every packet carries, plus a single int32 open-interest value.
# Nothing else. No timestamp, no price, no day high/low OI (those exist
# only inside the Full packet, code 8, which this decoder still does not
# implement). No additional field is inferred here: the documented
# layout is exactly one int32 and this decoder reads exactly one int32.
#
# SIGNEDNESS. The wire field is a documented int32 and is decoded with
# the signed `i` code, exactly as the Quote packet's volume/quantity
# fields already are, so a value Dhan sends is reproduced faithfully
# rather than reinterpreted as a huge unsigned number. Open interest is
# a contract COUNT and can never legitimately be negative; this decoder
# still reports whatever the wire said (its job is faithful decoding),
# and the DOMAIN boundary (`OIObservation`) is where a negative value is
# rejected rather than archived.
_OI_BODY_STRUCT = struct.Struct("<i")
_OI_PACKET_SIZE = _HEADER_SIZE + _OI_BODY_STRUCT.size  # == 12

# Dhan's documented exchange-segment code for NSE F&O (VERIFIED 64.76:
# "the same `NSE_FNO` (code 2) segment"). Open interest exists ONLY in
# the derivatives segment - a cash-equity instrument has no open
# interest at all - so an OI packet claiming any other segment is a
# packet this decoder refuses to interpret rather than one it silently
# accepts. Only this ONE segment code is named, because it is the only
# one this project has verified from Dhan's own documentation; no other
# segment's numeric code is guessed here.
NSE_FNO_SEGMENT_CODE = 2

# Disconnect packet (code 50): header + int16 disconnect reason code.
_DISCONNECT_BODY_STRUCT = struct.Struct("<h")
_DISCONNECT_PACKET_SIZE = _HEADER_SIZE + _DISCONNECT_BODY_STRUCT.size


class DhanFeedResponseCode(IntEnum):
    """Only the codes this decoder actually acts on are named as
    members - every OTHER documented code (6/8/...) is still
    correctly recognized as UNSUPPORTED_PACKET_TYPE by
    `decode_packet()` below, never silently misinterpreted as one of
    these four.

    Checkpoint 64.78 adds OPEN_INTEREST (5), which until now was
    correctly-but-uselessly classified UNSUPPORTED_PACKET_TYPE.

    THESE ARE RESPONSE CODES, NOT REQUEST CODES. They are two different,
    non-overlapping enumerations in Dhan's own Annexure and must never be
    confused: a client SUBSCRIBES with a RequestCode (17 = Subscribe
    Quote, 18 = Unsubscribe Quote - see `run_market_data_worker.py`) and
    the server REPLIES with packets carrying these feed response codes.
    In particular there is NO "subscribe to OI" request code 5: OI
    arrives as a response packet on an existing subscription, so nothing
    in the subscription layer may ever send a `5`."""

    TICKER = 2
    QUOTE = 4
    OPEN_INTEREST = 5
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
    UNSUPPORTED_SEGMENT = 4
    """Checkpoint 64.78: a well-formed packet of a supported type whose
    header names an exchange segment for which that packet type cannot
    meaningfully exist - currently only an OI packet (code 5) claiming a
    segment other than NSE_FNO, since open interest is a derivatives-only
    quantity. Distinct from UNSUPPORTED_PACKET_TYPE so a diagnostic can
    tell "we do not decode this packet shape" apart from "this packet
    shape arrived describing an instrument that cannot have it"."""
    INVALID_SECURITY_ID = 5
    """Checkpoint 64.78: the header parsed but carries a non-positive
    `security_id`, so the packet does not address any instrument. Never
    accepted and then dropped later: an unaddressable observation cannot
    be attributed to a contract, and decoding it further would only
    produce a value with nowhere to belong."""
    MALFORMED_LENGTH = 6
    """Checkpoint 64.78: the packet is LONGER than its documented fixed
    size. Applied to the OI packet (code 5) only, whose documented size
    is exactly 12 bytes. The pre-existing Ticker/Quote/Disconnect paths
    keep their historical `len(raw) >= size` tolerance unchanged - this
    checkpoint does not retroactively tighten packet types that have
    already run against a real feed. For the NEW packet type, extra
    trailing bytes mean the frame is not the thing it claims to be, and
    decoding its first 12 bytes anyway would be exactly the "silently
    decode a malformed packet" this checkpoint forbids."""


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
    to misinterpret as local time or milliseconds.

    Checkpoint 64.71: that conversion now goes through
    `normalize_dhan_websocket_timestamp()`, which corrects Dhan's
    IST-labelled WebSocket epoch to true UTC (2,154 real 64.70
    observations showed it running exactly +5h30m ahead of receipt).
    The resulting value is still, as always, timezone-aware UTC - only
    its correctness improved."""


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
class DhanOpenInterestPacket:
    """Checkpoint 64.78: the decoded OI packet (feed response code 5).

    Carries ONLY what the 12-byte wire layout carries: the shared header
    and one int32 open-interest value. It deliberately has NO timestamp
    field - the packet has none, and synthesising one here would put a
    fabricated instant inside a "decoded provider fact" object. The
    ingesting side stamps its own receipt instant when it builds the
    domain `OIObservation`."""

    header: DhanPacketHeader
    open_interest: int


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


DecodedDhanPacket = (
    DhanTickerPacket
    | DhanQuotePacket
    | DhanOpenInterestPacket
    | DhanDisconnectPacket
    | PacketDecodeFailure
)


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
            last_trade_time=normalize_dhan_websocket_timestamp(ltt_epoch),
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
            last_trade_time=normalize_dhan_websocket_timestamp(ltt_epoch),
            average_trade_price=atp,
            volume=volume,
            total_sell_quantity=total_sell_qty,
            total_buy_quantity=total_buy_qty,
            day_open=day_open,
            day_close=day_close,
            day_high=day_high,
            day_low=day_low,
        )

    if header.feed_response_code == DhanFeedResponseCode.OPEN_INTEREST:
        # Checkpoint 64.78. Validation order is deliberate: SHAPE first
        # (can these bytes even be an OI packet?), then ADDRESSABILITY
        # (does it name a real instrument?), then SEGMENT (can that
        # instrument have open interest at all?). Each failure keeps its
        # own distinct reason so a diagnostic never has to guess which
        # of the three went wrong.
        if len(raw) < _OI_PACKET_SIZE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.TRUNCATED_BODY,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        if len(raw) > _OI_PACKET_SIZE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.MALFORMED_LENGTH,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        if header.security_id <= 0:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.INVALID_SECURITY_ID,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        if header.exchange_segment_code != NSE_FNO_SEGMENT_CODE:
            return PacketDecodeFailure(
                reason=PacketDecodeFailureReason.UNSUPPORTED_SEGMENT,
                raw_length=len(raw),
                feed_response_code=header.feed_response_code,
            )
        (open_interest,) = _OI_BODY_STRUCT.unpack(raw[_HEADER_SIZE:_OI_PACKET_SIZE])
        return DhanOpenInterestPacket(header=header, open_interest=open_interest)

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
