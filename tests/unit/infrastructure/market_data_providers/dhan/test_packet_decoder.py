# tests/unit/infrastructure/market_data_providers/dhan/test_packet_decoder.py
#
# Checkpoint 53: coverage for the Dhan v2 binary packet decoder. Every
# fixture byte layout is constructed directly from the VERIFIED_PRIMARY
# facts in docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md
# (header + Ticker + Disconnect shapes, little-endian) - no live
# connection is needed to test a decoder against known-correct bytes.
from __future__ import annotations

import struct
from datetime import UTC, datetime

from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanDisconnectPacket,
    DhanTickerPacket,
    PacketDecodeFailure,
    PacketDecodeFailureReason,
    decode_header,
    decode_packet,
)

_HEADER_STRUCT = struct.Struct("<BHBi")


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int, segment: int = 1) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    header = _HEADER_STRUCT.pack(2, len(body), segment, security_id)
    return header + body


def _disconnect_bytes(*, security_id: int, reason_code: int, segment: int = 1) -> bytes:
    body = struct.pack("<h", reason_code)
    header = _HEADER_STRUCT.pack(50, len(body), segment, security_id)
    return header + body


def test_decodes_a_valid_ticker_packet() -> None:
    raw = _ticker_bytes(security_id=1333, ltp=2885.5, ltt_epoch=1735900800)

    result = decode_packet(raw)

    assert isinstance(result, DhanTickerPacket)
    assert result.header.feed_response_code == 2
    assert result.header.security_id == 1333
    assert result.header.exchange_segment_code == 1
    assert abs(result.last_traded_price - 2885.5) < 0.01  # float32 rounding
    assert result.last_trade_time == datetime.fromtimestamp(1735900800, tz=UTC)


def test_decodes_a_valid_disconnect_packet() -> None:
    raw = _disconnect_bytes(security_id=0, reason_code=805)

    result = decode_packet(raw)

    assert isinstance(result, DhanDisconnectPacket)
    assert result.disconnect_reason_code == 805


def test_truncated_header_never_raises_and_is_classified_correctly() -> None:
    raw = b"\x02\x00"  # far short of the 8-byte header

    result = decode_packet(raw)

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.TRUNCATED_HEADER
    assert result.feed_response_code is None


def test_truncated_body_never_raises_and_is_classified_correctly() -> None:
    full = _ticker_bytes(security_id=1333, ltp=100.0, ltt_epoch=1735900800)
    raw = full[:10]  # a valid header, but the body is cut short

    result = decode_packet(raw)

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.TRUNCATED_BODY
    assert result.feed_response_code == 2


def test_unsupported_but_syntactically_valid_packet_type_never_raises() -> None:
    """Feed response code 4 (Quote) is a REAL, documented Dhan packet
    type this checkpoint's decoder does not implement - it must be
    recognized and refused explicitly, never silently misread as a
    Ticker or crash the caller."""
    body = b"\x00" * 42  # Quote packet's real documented body size - irrelevant here
    header = _HEADER_STRUCT.pack(4, len(body), 1, 1333)
    raw = header + body

    result = decode_packet(raw)

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.UNSUPPORTED_PACKET_TYPE
    assert result.feed_response_code == 4


def test_empty_bytes_never_raises() -> None:
    result = decode_packet(b"")

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.TRUNCATED_HEADER
    assert result.raw_length == 0


def test_decode_header_returns_none_for_short_input() -> None:
    assert decode_header(b"\x02") is None


def test_decode_header_reads_every_field_correctly_in_isolation() -> None:
    raw = _ticker_bytes(security_id=99999, ltp=1.0, ltt_epoch=1735900800, segment=5)

    header = decode_header(raw)

    assert header is not None
    assert header.feed_response_code == 2
    assert header.exchange_segment_code == 5
    assert header.security_id == 99999
