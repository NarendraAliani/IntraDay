# tests/unit/infrastructure/market_data_providers/dhan/test_packet_decoder.py
#
# Checkpoint 53: coverage for the Dhan v2 binary packet decoder. Every
# fixture byte layout is constructed directly from the VERIFIED_PRIMARY
# facts in docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md
# (header + Ticker + Disconnect shapes, little-endian) - no live
# connection is needed to test a decoder against known-correct bytes.
from __future__ import annotations

import struct

from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanDisconnectPacket,
    DhanQuotePacket,
    DhanTickerPacket,
    PacketDecodeFailure,
    PacketDecodeFailureReason,
    decode_header,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_normalization import (
    normalize_dhan_websocket_timestamp,
)

_HEADER_STRUCT = struct.Struct("<BHBi")


def _ticker_bytes(*, security_id: int, ltp: float, ltt_epoch: int, segment: int = 1) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    header = _HEADER_STRUCT.pack(2, len(body), segment, security_id)
    return header + body


def _quote_bytes(
    *,
    security_id: int,
    ltp: float,
    ltq: int,
    ltt_epoch: int,
    atp: float,
    volume: int,
    total_sell_qty: int,
    total_buy_qty: int,
    day_open: float,
    day_close: float,
    day_high: float,
    day_low: float,
    segment: int = 1,
) -> bytes:
    body = struct.pack(
        "<fhifiiiffff",
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
    )
    header = _HEADER_STRUCT.pack(4, len(body), segment, security_id)
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
    assert result.last_trade_time == normalize_dhan_websocket_timestamp(1735900800)


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
    """Feed response code 8 (Full) is a REAL, documented Dhan packet type
    this decoder still does not implement - it must be recognized and
    refused explicitly, never silently misread as a Ticker/Quote or
    crash the caller.

    CHECKPOINT 64.78 UPDATE: this test previously used code 5 (OI) as
    its example of an unimplemented-but-real packet type. 64.78
    IMPLEMENTS code 5 (see `test_checkpoint_64_78_option_observations.
    py`), so continuing to assert that code 5 is unsupported would be
    asserting the opposite of the intended behaviour. The property under
    test - "a real documented packet type this decoder does not
    implement is refused explicitly rather than misread" - is unchanged
    and is now exercised against the Full packet, which genuinely
    remains unimplemented."""
    body = b"\x00" * 4
    header = _HEADER_STRUCT.pack(8, len(body), 1, 1333)
    raw = header + body

    result = decode_packet(raw)

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.UNSUPPORTED_PACKET_TYPE
    assert result.feed_response_code == 8


def test_decodes_a_valid_quote_packet() -> None:
    raw = _quote_bytes(
        security_id=1333,
        ltp=1650.25,
        ltq=10,
        ltt_epoch=1735900800,
        atp=1648.5,
        volume=125000,
        total_sell_qty=5000,
        total_buy_qty=6000,
        day_open=1640.0,
        day_close=1635.0,
        day_high=1655.0,
        day_low=1630.0,
    )

    result = decode_packet(raw)

    assert isinstance(result, DhanQuotePacket)
    assert result.header.security_id == 1333
    assert abs(result.last_traded_price - 1650.25) < 0.01
    assert result.last_traded_quantity == 10
    assert result.last_trade_time == normalize_dhan_websocket_timestamp(1735900800)
    assert abs(result.average_trade_price - 1648.5) < 0.01
    assert result.volume == 125000
    assert result.total_sell_quantity == 5000
    assert result.total_buy_quantity == 6000
    assert abs(result.day_open - 1640.0) < 0.01
    assert abs(result.day_close - 1635.0) < 0.01
    assert abs(result.day_high - 1655.0) < 0.01
    assert abs(result.day_low - 1630.0) < 0.01


def test_truncated_quote_body_is_classified_correctly() -> None:
    full = _quote_bytes(
        security_id=1333,
        ltp=100.0,
        ltq=1,
        ltt_epoch=1735900800,
        atp=100.0,
        volume=1,
        total_sell_qty=1,
        total_buy_qty=1,
        day_open=100.0,
        day_close=100.0,
        day_high=100.0,
        day_low=100.0,
    )
    raw = full[:20]  # valid header, body cut short

    result = decode_packet(raw)

    assert isinstance(result, PacketDecodeFailure)
    assert result.reason is PacketDecodeFailureReason.TRUNCATED_BODY
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
