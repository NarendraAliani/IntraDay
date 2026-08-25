# tests/unit/research/test_checkpoint_64_78_option_observations.py
#
# Checkpoint 64.78: deterministic, 100% OFFLINE verification of the
# option observation layer.
#
# NO live Dhan connection, NO WebSocket, NO REST call, NO downloaded
# instrument master, NO credential read. Every byte of every packet here
# is constructed by `struct.pack` in this file, and every contract comes
# from the SYNTHETIC 64.77 scrip-master fixture (security_ids in the
# obviously-fake 9000000+ range).
from __future__ import annotations

import struct
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.options import (
    OptionContractIdentityError,
    OptionInstrumentRecord,
    OptionType,
    OptionUnderlyingClass,
    require_stock_option,
)
from intraday.domain.market_data.archive import trading_date_for
from intraday.domain.market_data.option_observations import (
    OIObservation,
    OptionObservationError,
    OptionQuote,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    parse_option_scrip_master,
)
from intraday.infrastructure.market_data_providers.dhan.option_subscription import (
    NSE_EQ_SEGMENT,
    NSE_FNO_SEGMENT,
    option_subscription_instruments,
)
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    NSE_FNO_SEGMENT_CODE,
    DhanFeedResponseCode,
    DhanOpenInterestPacket,
    DhanQuotePacket,
    PacketDecodeFailure,
    PacketDecodeFailureReason,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_option_observation import (
    DHAN_WEBSOCKET_SOURCE,
    OptionObservationRejectionReason,
    build_security_id_to_option_record_map,
    convert_packet_to_oi_observation,
    convert_packet_to_option_quote,
)
from tests.unit.research.checkpoint_64_77_option_fixtures import (
    EXPIRY_FAR,
    EXPIRY_NEAR,
    RELIANCE,
    SCRIP_MASTER_CSV,
)

# --- Synthetic packet builders ---------------------------------------
_HEADER_STRUCT = struct.Struct("<BHBi")
_QUOTE_BODY_STRUCT = struct.Struct("<fhifiiiffff")

RELIANCE_SEP_2400_CE_SECURITY_ID = 9000001
RELIANCE_SEP_2400_PE_SECURITY_ID = 9000002
RELIANCE_OCT_2500_CE_SECURITY_ID = 9000007
INDEX_OPTION_SECURITY_ID = 9000101
UNKNOWN_SECURITY_ID = 9999999

OBSERVED_AT = datetime(2026, 9, 15, 5, 30, 0, tzinfo=UTC)  # 11:00 IST
LTT_EPOCH = 1789000000


def _header(*, code: int, segment: int, security_id: int, length: int = 4) -> bytes:
    return _HEADER_STRUCT.pack(code, length, segment, security_id)


def _oi_packet(
    *,
    open_interest: int,
    security_id: int = RELIANCE_SEP_2400_CE_SECURITY_ID,
    segment: int = NSE_FNO_SEGMENT_CODE,
) -> bytes:
    """A synthetic, documented-shape OI packet: feed response code 5,
    the shared 8-byte header, one int32 - exactly 12 bytes."""
    return _header(code=5, segment=segment, security_id=security_id) + struct.pack(
        "<i", open_interest
    )


def _quote_packet(
    *,
    security_id: int,
    last_price: float = 42.5,
    volume: int = 12_500,
    segment: int = NSE_FNO_SEGMENT_CODE,
    day_open: float = 40.0,
    day_close: float = 39.0,
    day_high: float = 45.0,
    day_low: float = 38.0,
) -> bytes:
    return _header(code=4, segment=segment, security_id=security_id, length=42) + (
        _QUOTE_BODY_STRUCT.pack(
            last_price,
            50,
            LTT_EPOCH,
            41.0,
            volume,
            100,
            120,
            day_open,
            day_close,
            day_high,
            day_low,
        )
    )


@pytest.fixture(scope="module")
def records() -> tuple[OptionInstrumentRecord, ...]:
    """Parsed from the SYNTHETIC 64.77 fixture - includes the OPTIDX row
    on purpose, so exclusion is tested against a mixed universe."""
    return parse_option_scrip_master(SCRIP_MASTER_CSV)


@pytest.fixture(scope="module")
def resolution_index(
    records: tuple[OptionInstrumentRecord, ...],
) -> dict[int, OptionInstrumentRecord]:
    return build_security_id_to_option_record_map(records)


def _contract(records: tuple[OptionInstrumentRecord, ...], security_id: int):
    for record in records:
        if record.provider_identity.security_id == security_id:
            return record.contract
    raise AssertionError(f"fixture has no contract for {security_id}")


# =====================================================================
# PHASE 4 / 16 - Dhan OI packet, feed response code 5
# =====================================================================
def test_oi_packet_code_5_is_no_longer_unsupported() -> None:
    """The exact behaviour change this checkpoint makes: 64.76 recorded
    code 5 as UNSUPPORTED_PACKET_TYPE."""
    decoded = decode_packet(_oi_packet(open_interest=123_456))

    assert isinstance(decoded, DhanOpenInterestPacket)
    assert decoded.header.feed_response_code == DhanFeedResponseCode.OPEN_INTEREST
    assert decoded.header.feed_response_code == 5
    assert decoded.open_interest == 123_456
    assert decoded.header.security_id == RELIANCE_SEP_2400_CE_SECURITY_ID
    assert decoded.header.exchange_segment_code == NSE_FNO_SEGMENT_CODE


def test_a_valid_oi_packet_is_exactly_twelve_bytes() -> None:
    assert len(_oi_packet(open_interest=1)) == 12


def test_oi_packet_of_wrong_length_is_rejected_not_decoded() -> None:
    """(B) wrong length: trailing bytes mean this frame is not the thing
    it claims to be; decoding its first 12 bytes anyway would be exactly
    the silent decode of a malformed packet this checkpoint forbids."""
    decoded = decode_packet(_oi_packet(open_interest=99) + b"\x00\x00")

    assert isinstance(decoded, PacketDecodeFailure)
    assert decoded.reason is PacketDecodeFailureReason.MALFORMED_LENGTH
    assert decoded.feed_response_code == 5


def test_truncated_oi_packet_is_rejected() -> None:
    decoded = decode_packet(_oi_packet(open_interest=99)[:10])

    assert isinstance(decoded, PacketDecodeFailure)
    assert decoded.reason is PacketDecodeFailureReason.TRUNCATED_BODY


def test_oi_packet_with_truncated_header_is_rejected() -> None:
    decoded = decode_packet(b"\x05\x04")

    assert isinstance(decoded, PacketDecodeFailure)
    assert decoded.reason is PacketDecodeFailureReason.TRUNCATED_HEADER
    assert decoded.feed_response_code is None


def test_oi_packet_in_a_non_fno_segment_is_rejected() -> None:
    """(D) invalid segment: a cash-equity instrument has no open
    interest, so an OI packet claiming that segment is not interpretable."""
    decoded = decode_packet(_oi_packet(open_interest=10, segment=1))

    assert isinstance(decoded, PacketDecodeFailure)
    assert decoded.reason is PacketDecodeFailureReason.UNSUPPORTED_SEGMENT


def test_oi_packet_with_invalid_security_id_is_rejected() -> None:
    decoded = decode_packet(_oi_packet(open_interest=10, security_id=0))

    assert isinstance(decoded, PacketDecodeFailure)
    assert decoded.reason is PacketDecodeFailureReason.INVALID_SECURITY_ID


def test_zero_open_interest_is_a_legitimate_reading() -> None:
    """A listed strike with no open positions really does print zero -
    it must not be confused with a decode failure."""
    decoded = decode_packet(_oi_packet(open_interest=0))

    assert isinstance(decoded, DhanOpenInterestPacket)
    assert decoded.open_interest == 0


def test_decoder_reports_a_negative_int32_faithfully_and_domain_rejects_it() -> None:
    """(F) documented int32 semantics. The DECODER's job is faithful
    decoding, so it reports what the wire said; the DOMAIN boundary is
    where a physically-impossible negative contract count is refused."""
    decoded = decode_packet(_oi_packet(open_interest=-5))
    assert isinstance(decoded, DhanOpenInterestPacket)
    assert decoded.open_interest == -5

    with pytest.raises(OptionObservationError):
        OIObservation(
            contract=_contract(
                parse_option_scrip_master(SCRIP_MASTER_CSV), RELIANCE_SEP_2400_CE_SECURITY_ID
            ),
            provider="DHAN",
            provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
            observed_at=OBSERVED_AT,
            open_interest=-5,
            data_source=DHAN_WEBSOCKET_SOURCE,
        )


def test_large_open_interest_round_trips_within_int32() -> None:
    decoded = decode_packet(_oi_packet(open_interest=2_147_483_647))
    assert isinstance(decoded, DhanOpenInterestPacket)
    assert decoded.open_interest == 2_147_483_647


def test_existing_packet_types_are_unchanged_by_the_oi_addition() -> None:
    """Regression guard: adding code 5 must not perturb the codes that
    have already run against a real feed."""
    quote = decode_packet(_quote_packet(security_id=RELIANCE_SEP_2400_CE_SECURITY_ID))
    assert isinstance(quote, DhanQuotePacket)

    unsupported = decode_packet(_header(code=6, segment=1, security_id=2885) + b"\x00" * 8)
    assert isinstance(unsupported, PacketDecodeFailure)
    assert unsupported.reason is PacketDecodeFailureReason.UNSUPPORTED_PACKET_TYPE


# =====================================================================
# PHASE 5 / 9 / 10 - packet -> canonical observation
# =====================================================================
def test_quote_packet_maps_to_an_option_quote(resolution_index) -> None:
    packet = decode_packet(_quote_packet(security_id=RELIANCE_SEP_2400_CE_SECURITY_ID))
    assert isinstance(packet, DhanQuotePacket)

    result = convert_packet_to_option_quote(packet, security_id_to_option=resolution_index)

    assert result.accepted
    quote = result.quote
    assert quote is not None
    assert quote.contract.underlying_symbol == RELIANCE
    assert quote.contract.expiry == EXPIRY_NEAR
    assert quote.contract.strike == Decimal("2400")
    assert quote.contract.option_type is OptionType.CE
    assert quote.last_price == Decimal("42.5")
    assert quote.cumulative_volume == Decimal("12500")
    assert quote.open_price == Decimal("40")
    assert quote.previous_close == Decimal("39")
    assert quote.provider_security_id == RELIANCE_SEP_2400_CE_SECURITY_ID
    assert quote.data_source == DHAN_WEBSOCKET_SOURCE


def test_strike_expiry_and_option_type_come_from_the_master_never_the_packet(
    resolution_index,
) -> None:
    """Phase 10's hard rule. Two packets identical in every byte except
    security_id resolve to genuinely different contracts - proof the
    identity came from the instrument master, since the packet carries
    no strike/expiry/CE-PE field at all."""
    ce = decode_packet(_quote_packet(security_id=RELIANCE_SEP_2400_CE_SECURITY_ID))
    pe = decode_packet(_quote_packet(security_id=RELIANCE_SEP_2400_PE_SECURITY_ID))
    far = decode_packet(_quote_packet(security_id=RELIANCE_OCT_2500_CE_SECURITY_ID))
    assert isinstance(ce, DhanQuotePacket)
    assert isinstance(pe, DhanQuotePacket)
    assert isinstance(far, DhanQuotePacket)

    ce_quote = convert_packet_to_option_quote(ce, security_id_to_option=resolution_index).quote
    pe_quote = convert_packet_to_option_quote(pe, security_id_to_option=resolution_index).quote
    far_quote = convert_packet_to_option_quote(far, security_id_to_option=resolution_index).quote

    assert ce_quote is not None and pe_quote is not None and far_quote is not None
    assert ce_quote.contract.option_type is OptionType.CE
    assert pe_quote.contract.option_type is OptionType.PE
    assert far_quote.contract.expiry == EXPIRY_FAR
    assert far_quote.contract.strike == Decimal("2500")
    assert len({ce_quote.contract_id, pe_quote.contract_id, far_quote.contract_id}) == 3


def test_unresolvable_security_id_is_rejected_never_fabricated(resolution_index) -> None:
    packet = decode_packet(_quote_packet(security_id=UNKNOWN_SECURITY_ID))
    assert isinstance(packet, DhanQuotePacket)

    result = convert_packet_to_option_quote(packet, security_id_to_option=resolution_index)

    assert not result.accepted
    assert result.quote is None
    assert result.rejected_reason is OptionObservationRejectionReason.UNRESOLVED_SECURITY_ID


def test_index_option_observation_is_rejected_at_the_routing_boundary(resolution_index) -> None:
    packet = decode_packet(_quote_packet(security_id=INDEX_OPTION_SECURITY_ID))
    assert isinstance(packet, DhanQuotePacket)

    result = convert_packet_to_option_quote(packet, security_id_to_option=resolution_index)

    assert result.rejected_reason is OptionObservationRejectionReason.INDEX_OPTION_NOT_IN_SCOPE


def test_non_positive_premium_is_rejected(resolution_index) -> None:
    packet = decode_packet(
        _quote_packet(security_id=RELIANCE_SEP_2400_CE_SECURITY_ID, last_price=0.0)
    )
    assert isinstance(packet, DhanQuotePacket)

    result = convert_packet_to_option_quote(packet, security_id_to_option=resolution_index)

    assert result.rejected_reason is OptionObservationRejectionReason.NON_POSITIVE_PREMIUM


def test_oi_packet_maps_to_an_oi_observation(resolution_index) -> None:
    """(G) provider-to-domain mapping for the OI path."""
    packet = decode_packet(_oi_packet(open_interest=87_500))
    assert isinstance(packet, DhanOpenInterestPacket)

    result = convert_packet_to_oi_observation(
        packet, security_id_to_option=resolution_index, observed_at=OBSERVED_AT
    )

    assert result.accepted
    observation = result.observation
    assert observation is not None
    assert observation.open_interest == 87_500
    assert observation.observed_at == OBSERVED_AT
    assert observation.contract.underlying_symbol == RELIANCE
    assert observation.data_source == DHAN_WEBSOCKET_SOURCE


def test_oi_observation_is_independent_of_any_option_quote(resolution_index) -> None:
    """Phase 3: OI arrives in its own packet and must be creatable with
    no quote in sight - the whole reason it is a separate contract."""
    packet = decode_packet(_oi_packet(open_interest=5))
    assert isinstance(packet, DhanOpenInterestPacket)

    result = convert_packet_to_oi_observation(
        packet, security_id_to_option=resolution_index, observed_at=OBSERVED_AT
    )

    assert result.accepted
    assert not hasattr(result.observation, "last_price")


def test_option_quote_carries_no_oi_iv_or_greeks_field() -> None:
    """Scope guard: IV/Greeks/OptionChain are explicitly DEFERRED, and
    OI lives in its own contract because Dhan delivers it separately."""
    fields = set(OptionQuote.__dataclass_fields__)
    assert not fields & {
        "open_interest",
        "oi",
        "oi_change",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
    }
    assert "open_interest" not in set(OptionQuote.__dataclass_fields__)
    assert "last_price" not in set(OIObservation.__dataclass_fields__)


def test_oi_observation_stores_no_derived_oi_change() -> None:
    assert "oi_change" not in set(OIObservation.__dataclass_fields__)
    assert "previous_oi" not in set(OIObservation.__dataclass_fields__)


def test_unresolved_oi_packet_is_rejected(resolution_index) -> None:
    packet = decode_packet(_oi_packet(open_interest=1, security_id=UNKNOWN_SECURITY_ID))
    assert isinstance(packet, DhanOpenInterestPacket)

    result = convert_packet_to_oi_observation(
        packet, security_id_to_option=resolution_index, observed_at=OBSERVED_AT
    )

    assert result.rejected_reason is OptionObservationRejectionReason.UNRESOLVED_SECURITY_ID


# =====================================================================
# PHASE 6 / 7 / 8 / 17 - NSE_FNO subscription
# =====================================================================
def test_nse_fno_subscription_is_emitted_with_the_right_segment(records) -> None:
    import json

    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        SUBSCRIBE_REQUEST_CODE_QUOTE,
        _build_subscribe_messages,
    )

    instruments = option_subscription_instruments(records)
    messages = _build_subscribe_messages(instruments)

    assert len(messages) == 1
    payload = json.loads(messages[0])
    assert payload["RequestCode"] == SUBSCRIBE_REQUEST_CODE_QUOTE == 17
    assert payload["InstrumentCount"] == 8  # 8 RELIANCE stock options
    assert {entry["ExchangeSegment"] for entry in payload["InstrumentList"]} == {NSE_FNO_SEGMENT}
    assert str(RELIANCE_SEP_2400_CE_SECURITY_ID) in {
        entry["SecurityId"] for entry in payload["InstrumentList"]
    }


def test_optidx_contracts_never_enter_the_active_subscription(records) -> None:
    instruments = option_subscription_instruments(records)

    assert all(i.security_id != INDEX_OPTION_SECURITY_ID for i in instruments)
    index_contracts = [
        r.contract for r in records if r.contract.underlying_class is OptionUnderlyingClass.INDEX
    ]
    assert index_contracts, "fixture must contain an OPTIDX row for this test to mean anything"
    with pytest.raises(OptionContractIdentityError):
        require_stock_option(index_contracts[0])


def test_nse_eq_subscription_remains_unchanged(records) -> None:
    """(A) The equity path is untouched: an equity DhanInstrument still
    defaults to NSE_EQ and still encodes exactly as before."""
    import json

    from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        _build_subscribe_messages,
    )

    equity = (DhanInstrument(symbol="RELIANCE", security_id=2885),)
    payload = json.loads(_build_subscribe_messages(equity)[0])

    assert equity[0].exchange_segment == NSE_EQ_SEGMENT == "NSE_EQ"
    assert payload["RequestCode"] == 17
    assert payload["InstrumentList"] == [{"ExchangeSegment": "NSE_EQ", "SecurityId": "2885"}]


def test_option_batching_respects_the_documented_hundred_limit_and_is_deterministic(
    records,
) -> None:
    """(C)(D)(E): batching, the unchanged 100-per-message limit, and
    byte-identical repeated runs, all via the SAME builder equities use."""
    import json

    from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        _build_subscribe_messages,
    )

    many = tuple(
        DhanInstrument(symbol=f"OPT{i}", security_id=9100000 + i, exchange_segment=NSE_FNO_SEGMENT)
        for i in range(250)
    )
    messages = _build_subscribe_messages(many)

    assert [json.loads(m)["InstrumentCount"] for m in messages] == [100, 100, 50]
    assert all(json.loads(m)["InstrumentCount"] <= 100 for m in messages)
    assert messages == _build_subscribe_messages(many)


def test_unsubscribe_uses_the_documented_quote_unsubscribe_code(records) -> None:
    """(G) request code 18 - and never a `5`, which is a RESPONSE code."""
    import json

    from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
        UNSUBSCRIBE_REQUEST_CODE_QUOTE,
        _build_unsubscribe_messages,
    )

    messages = _build_unsubscribe_messages(option_subscription_instruments(records))
    payload = json.loads(messages[0])

    assert UNSUBSCRIBE_REQUEST_CODE_QUOTE == 18
    assert payload["RequestCode"] == 18
    assert payload["RequestCode"] != 5
    assert payload["InstrumentCount"] == 8


# =====================================================================
# PHASE 2 / 3 - domain contract invariants
# =====================================================================
def test_option_quote_rejects_a_non_positive_premium(records) -> None:
    with pytest.raises(OptionObservationError):
        OptionQuote(
            contract=_contract(records, RELIANCE_SEP_2400_CE_SECURITY_ID),
            provider="DHAN",
            provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
            timestamp=OBSERVED_AT,
            last_price=Decimal("0"),
        )


def test_option_quote_rejects_a_naive_timestamp(records) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - ensure_utc's own error type
        OptionQuote(
            contract=_contract(records, RELIANCE_SEP_2400_CE_SECURITY_ID),
            provider="DHAN",
            provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
            timestamp=datetime(2026, 9, 15, 11, 0, 0),  # noqa: DTZ001 - deliberately naive
            last_price=Decimal("42.5"),
        )


def test_option_quote_rejects_a_crossed_market(records) -> None:
    with pytest.raises(OptionObservationError):
        OptionQuote(
            contract=_contract(records, RELIANCE_SEP_2400_CE_SECURITY_ID),
            provider="DHAN",
            provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
            timestamp=OBSERVED_AT,
            last_price=Decimal("42.5"),
            bid=Decimal("43"),
            ask=Decimal("42"),
        )


def test_observations_carry_canonical_contract_identity(records) -> None:
    contract = _contract(records, RELIANCE_SEP_2400_CE_SECURITY_ID)
    quote = OptionQuote(
        contract=contract,
        provider="DHAN",
        provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
        timestamp=OBSERVED_AT,
        last_price=Decimal("42.5"),
    )
    oi = OIObservation(
        contract=contract,
        provider="DHAN",
        provider_security_id=RELIANCE_SEP_2400_CE_SECURITY_ID,
        observed_at=OBSERVED_AT,
        open_interest=100,
    )

    assert quote.contract_id == oi.contract_id == contract.contract_id
    assert str(quote.contract_id) == "NSE:FNO:RELIANCE:2026-09-24:2400:CE"


def test_trading_date_uses_the_canonical_ist_derivation() -> None:
    """Phase 13: the 03:45-05:30 UTC window where a naive `.date()`
    would file an NSE morning observation under the previous day."""
    opening = datetime(2026, 9, 15, 3, 50, tzinfo=UTC)

    assert trading_date_for(opening).isoformat() == "2026-09-15"
    assert opening.date().isoformat() == "2026-09-15"
    late_evening = datetime(2026, 9, 14, 20, 0, tzinfo=UTC)
    assert trading_date_for(late_evening).isoformat() == "2026-09-15"
