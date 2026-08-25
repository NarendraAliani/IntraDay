# File: tests/unit/research/test_checkpoint_64_76_dhan_option_capability.py
#
# Checkpoint 64.76: CAPABILITY-VERIFICATION tests for Dhan's documented
# stock-option data contract.
#
# This checkpoint is research, NOT implementation - no options schema,
# no OptionChainModel/GreeksModel/OIModel, no live Dhan connection. What
# these tests DO is freeze the handful of facts that were verified this
# checkpoint against Dhan's own official documentation, in exactly the
# pattern Checkpoint 64.71 established for `SUBSCRIBE_REQUEST_CODE_QUOTE
# = 17`: a documented provider constant asserted as a literal, so that a
# future implementation checkpoint cannot silently drift away from the
# published enum, and so the CURRENT gaps are recorded as executable
# facts rather than prose someone has to remember.
#
# Sources (fetched this checkpoint, official Dhan documentation only):
#   * https://dhanhq.co/docs/v2/annexure/        - segment/feed enums
#   * https://dhanhq.co/docs/v2/live-market-feed/ - packet codes
#   * https://dhanhq.co/docs/v2/option-chain/     - chain/greeks fields
#
# DETERMINISTIC and OFFLINE: no socket, no HTTP, no Dhan, no database.
# Every packet below is synthesised in-process from the documented byte
# layout. NOTHING here invents a response fixture for an undocumented
# field - the OI packet's 12-byte layout and the option-chain field
# NAMES are both explicitly published by Dhan; no Greeks or IV wire
# fixture is fabricated, because Dhan publishes those only as a REST
# JSON schema, which this checkpoint does not implement.
from __future__ import annotations

import struct

from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instruments import NSE_EQ_SEGMENT
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    HEADER_SIZE,
    DhanOpenInterestPacket,
    PacketDecodeFailure,
    decode_header,
    decode_packet,
)

# --- Documented Dhan enums (VERIFIED, official Annexure) ---------------------
# Exchange-segment codes. NSE_FNO = 2 is the segment EVERY NSE stock
# option lives in - the project currently speaks only NSE_EQ = 1.
DOCUMENTED_SEGMENT_CODE_NSE_EQ = 1
DOCUMENTED_SEGMENT_CODE_NSE_FNO = 2

# Feed response codes. Code 5 (OI) is the one that carries open interest
# for derivatives; Dhan documents that it arrives ALONGSIDE Quote-mode
# subscriptions rather than needing a subscription of its own.
DOCUMENTED_FEED_RESPONSE_CODE_OI = 5
DOCUMENTED_OI_PACKET_SIZE = 12  # 8-byte header + int32 open interest


def _oi_packet(*, security_id: int, open_interest: int) -> bytes:
    """Build a documented 12-byte OI packet (little-endian, per Dhan's
    published layout). Synthetic, not captured from a live feed."""
    header = struct.pack(
        "<BHBi",
        DOCUMENTED_FEED_RESPONSE_CODE_OI,
        4,  # payload length
        DOCUMENTED_SEGMENT_CODE_NSE_FNO,
        security_id,
    )
    return header + struct.pack("<i", open_interest)


class TestDocumentedOptionSegment:
    def test_nse_fno_segment_code_differs_from_nse_eq(self) -> None:
        """Stock options are NOT in the segment this project subscribes
        to today. Recorded so the difference is explicit, not assumed."""
        assert DOCUMENTED_SEGMENT_CODE_NSE_FNO != DOCUMENTED_SEGMENT_CODE_NSE_EQ

    def test_project_live_universe_is_still_equity_only(self) -> None:
        """The current live-quote universe pins NSE_EQ. This is the
        precise, single-line location a future options checkpoint must
        generalise - asserted so that generalisation is a deliberate,
        test-visible act."""
        assert NSE_EQ_SEGMENT == "NSE_EQ"

    def test_domain_exchange_enum_has_no_derivatives_segment(self) -> None:
        """The shared-kernel `Exchange` vocabulary is cash-equity only
        (NSE/BSE). An option contract's identity needs a segment concept
        this enum does not currently carry. Documented as a real
        architectural gap - deliberately NOT fixed this checkpoint."""
        assert {member.value for member in Exchange} == {"NSE", "BSE"}


class TestOiPacketIsDocumentedButUnimplemented:
    """Dhan DOES stream open interest (feed response code 5).

    CHECKPOINT 64.78 CLOSED THE OTHER HALF OF THIS CLASS'S ORIGINAL
    CLAIM. At 64.76 the decoder did NOT decode code 5, and this class
    asserted both halves so the gap could not be misread in either
    direction. 64.78 implements code 5, so the "unimplemented" half is
    now obsolete and is updated here deliberately rather than deleted -
    the class name is kept so the history of the finding stays
    traceable to its checkpoint.

    What remains asserted, and still matters: Dhan's documented WIRE
    FACTS (12-byte packet, 8-byte header, feed response code 5, NSE_FNO
    segment code 2, int32 payload). Those are provider facts, not
    implementation details, and the decoder must keep honouring them."""

    def test_oi_packet_header_decodes_with_documented_shape(self) -> None:
        raw = _oi_packet(security_id=54321, open_interest=1_234_500)
        assert len(raw) == DOCUMENTED_OI_PACKET_SIZE

        header = decode_header(raw)
        assert header is not None
        assert header.feed_response_code == DOCUMENTED_FEED_RESPONSE_CODE_OI
        assert header.exchange_segment_code == DOCUMENTED_SEGMENT_CODE_NSE_FNO
        assert header.security_id == 54321

    def test_oi_packet_is_decoded_faithfully_and_never_misdecoded(self) -> None:
        """The critical safety property, CARRIED FORWARD not weakened.

        64.76 asserted it as "an OI packet is classified
        UNSUPPORTED_PACKET_TYPE"; 64.78 implements code 5, so the same
        property is now asserted in its stronger form: the packet is
        decoded into its OWN type, carrying the OI value that was really
        on the wire - never silently reinterpreted as a Ticker or Quote,
        and still never raising. Misreading it as an equity Ticker/Quote
        was, and remains, the failure this test exists to prevent.

        Full behavioural coverage of code 5 (malformed length, truncation,
        bad segment, invalid security_id, int32 edge values) lives in
        `test_checkpoint_64_78_option_observations.py`."""
        raw = _oi_packet(security_id=54321, open_interest=1_234_500)
        decoded = decode_packet(raw)

        assert isinstance(decoded, DhanOpenInterestPacket)
        assert not isinstance(decoded, PacketDecodeFailure)
        assert decoded.open_interest == 1_234_500
        assert decoded.header.feed_response_code == DOCUMENTED_FEED_RESPONSE_CODE_OI
        assert decoded.header.security_id == 54321

    def test_open_interest_payload_is_present_on_the_wire(self) -> None:
        """Proves the value is genuinely THERE and is recoverable from
        the documented layout - at 64.76 this proved the gap was
        decoder-side rather than a provider limitation; it now also
        pins the exact byte offset the 64.78 decoder must keep reading."""
        raw = _oi_packet(security_id=54321, open_interest=1_234_500)
        (open_interest,) = struct.unpack("<i", raw[HEADER_SIZE:DOCUMENTED_OI_PACKET_SIZE])
        assert open_interest == 1_234_500


class TestOptionChainDocumentedFieldNames:
    """Field NAMES only, quoted from Dhan's published Option Chain
    response schema. No values, no fabricated fixture - this asserts
    what a future implementation must map, and (by omission) what Dhan
    does not publish."""

    STRIKE_LEVEL_FIELDS = frozenset(
        {
            "average_price",
            "implied_volatility",
            "last_price",
            "oi",
            "previous_close_price",
            "previous_oi",
            "previous_volume",
            "security_id",
            "top_ask_price",
            "top_ask_quantity",
            "top_bid_price",
            "top_bid_quantity",
            "volume",
        }
    )
    GREEKS_FIELDS = frozenset({"delta", "theta", "gamma", "vega"})

    def test_iv_and_oi_are_provider_supplied_not_derived(self) -> None:
        assert "implied_volatility" in self.STRIKE_LEVEL_FIELDS
        assert "oi" in self.STRIKE_LEVEL_FIELDS

    def test_oi_change_requires_a_baseline_and_is_not_supplied_directly(self) -> None:
        """Dhan supplies `oi` and `previous_oi` - a PREVIOUS-DAY-CLOSE
        baseline. It does NOT publish an intraday `oi_change` field, so
        intraday OI delta must be computed against this project's own
        stored series."""
        assert "previous_oi" in self.STRIKE_LEVEL_FIELDS
        assert "oi_change" not in self.STRIKE_LEVEL_FIELDS

    def test_rho_is_not_published_by_dhan(self) -> None:
        """Four Greeks are published, not five. Rho would have to be
        DERIVED - recorded rather than assumed available."""
        assert {"delta", "theta", "gamma", "vega"} == self.GREEKS_FIELDS
        assert "rho" not in self.GREEKS_FIELDS

    def test_bid_ask_and_quantities_are_available_at_strike_level(self) -> None:
        assert {
            "top_bid_price",
            "top_ask_price",
            "top_bid_quantity",
            "top_ask_quantity",
        } <= self.STRIKE_LEVEL_FIELDS

    def test_chain_carries_no_timestamp_field(self) -> None:
        """A snapshot with no provider-stamped observation instant: the
        consumer must stamp its own `fetched_at`. Directly relevant to
        the 'exact market state at a Gainz signal timestamp' requirement
        - the chain alone cannot answer it."""
        assert not any("time" in name or "stamp" in name for name in self.STRIKE_LEVEL_FIELDS)
