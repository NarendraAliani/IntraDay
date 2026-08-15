# tests/unit/infrastructure/market_data_providers/dhan/test_packet_to_quote.py
#
# Checkpoint 54: coverage for the Dhan-packet -> canonical `Quote`
# bridge - the missing link Checkpoint 53 explicitly named as undone.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanPacketHeader,
    DhanQuotePacket,
    DhanTickerPacket,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    DHAN_WEBSOCKET_SOURCE,
    QuoteConversionRejectionReason,
    build_security_id_to_symbol_map,
    convert_packet_to_quote,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)

_SECURITY_MAP = {2885: "RELIANCE", 1333: "HDFCBANK"}


def _header(security_id: int) -> DhanPacketHeader:
    return DhanPacketHeader(
        feed_response_code=2, message_length=8, exchange_segment_code=1, security_id=security_id
    )


def test_converts_a_ticker_packet_to_the_canonical_quote() -> None:
    packet = DhanTickerPacket(header=_header(2885), last_traded_price=2900.5, last_trade_time=NOW)

    result = convert_packet_to_quote(packet, security_id_to_symbol=_SECURITY_MAP)

    assert result.accepted is True
    assert result.quote is not None
    assert result.quote.instrument_id == RELIANCE
    assert result.quote.last_price == Decimal("2900.5")
    assert result.quote.timestamp == NOW
    assert result.quote.source == DHAN_WEBSOCKET_SOURCE


def test_converts_a_quote_packet_using_only_its_ltp_and_ltt() -> None:
    packet = DhanQuotePacket(
        header=_header(1333),
        last_traded_price=1650.25,
        last_traded_quantity=10,
        last_trade_time=NOW,
        average_trade_price=1648.5,
        volume=125000,
        total_sell_quantity=5000,
        total_buy_quantity=6000,
        day_open=1640.0,
        day_close=1635.0,
        day_high=1655.0,
        day_low=1630.0,
    )

    result = convert_packet_to_quote(packet, security_id_to_symbol=_SECURITY_MAP)

    assert result.accepted is True
    assert result.quote is not None
    assert result.quote.instrument_id == make_instrument_id(Exchange.NSE, "HDFCBANK")
    assert result.quote.last_price == Decimal("1650.25")


def test_unknown_security_id_is_rejected_never_fabricated() -> None:
    packet = DhanTickerPacket(header=_header(999999), last_traded_price=100.0, last_trade_time=NOW)

    result = convert_packet_to_quote(packet, security_id_to_symbol=_SECURITY_MAP)

    assert result.accepted is False
    assert result.quote is None
    assert result.rejected_reason is QuoteConversionRejectionReason.UNKNOWN_SECURITY_ID


def test_non_positive_price_is_rejected_never_coerced() -> None:
    packet = DhanTickerPacket(header=_header(2885), last_traded_price=0.0, last_trade_time=NOW)

    result = convert_packet_to_quote(packet, security_id_to_symbol=_SECURITY_MAP)

    assert result.accepted is False
    assert result.rejected_reason is QuoteConversionRejectionReason.NON_POSITIVE_PRICE


def test_build_security_id_to_symbol_map_from_dhan_instruments() -> None:
    instruments = (
        DhanInstrument(symbol="RELIANCE", security_id=2885),
        DhanInstrument(symbol="TCS", security_id=11536),
    )

    mapping = build_security_id_to_symbol_map(instruments)

    assert mapping == {2885: "RELIANCE", 11536: "TCS"}
