# File: tests/unit/research/test_checkpoint_64_71_dhan_timestamp_normalization.py
#
# Checkpoint 64.71 proof suite for the Dhan WebSocket timestamp
# correction. Every test here uses FIXED, synthetic, or frozen-fixture
# time - never `datetime.now()` - so a failure always means the logic
# changed, never that the test was run at an awkward moment.
from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import BarStatus, aggregate_quotes_into_bars
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanQuotePacket,
    DhanTickerPacket,
    decode_packet,
)
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    convert_packet_to_quote,
)
from intraday.infrastructure.market_data_providers.dhan.timestamp_normalization import (
    IST_UTC_OFFSET,
    normalize_dhan_websocket_timestamp,
)
from tests.unit.research.checkpoint_64_70_timestamp_fixtures import parsed_observations

_HEADER = struct.Struct("<BHBi")
_IST_OFFSET_SECONDS = 19_800.0
_SECURITY_ID = 1333
_SYMBOL_MAP = {_SECURITY_ID: "RELIANCE"}
_DATA_SOURCE = "dhan_websocket"


def _ticker_packet_bytes(*, ltt_epoch: int, ltp: float = 100.0) -> bytes:
    body = struct.pack("<fi", ltp, ltt_epoch)
    return _HEADER.pack(2, len(body), 1, _SECURITY_ID) + body


def _quote_packet_bytes(*, ltt_epoch: int, ltp: float = 100.0, volume: int = 5000) -> bytes:
    body = struct.pack(
        "<fhifiiiffff", ltp, 10, ltt_epoch, ltp, volume, 1, 2, 99.0, 98.0, 101.0, 97.0
    )
    return _HEADER.pack(4, len(body), 1, _SECURITY_ID) + body


# --------------------------------------------------------------------
# 1. The conversion function itself
# --------------------------------------------------------------------


def test_normalization_subtracts_exactly_the_ist_offset() -> None:
    epoch = 1_700_000_000
    assert normalize_dhan_websocket_timestamp(epoch) == datetime.fromtimestamp(
        epoch, tz=UTC
    ) - timedelta(hours=5, minutes=30)


def test_ist_offset_constant_is_exactly_five_hours_thirty_minutes() -> None:
    assert IST_UTC_OFFSET.total_seconds() == _IST_OFFSET_SECONDS


def test_normalized_result_is_always_timezone_aware_utc() -> None:
    """Directive question B - the canonical domain contract is
    unchanged: still a tz-aware UTC datetime, just a correct one."""
    result = normalize_dhan_websocket_timestamp(1_700_000_000)
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


def test_normalization_is_exact_at_boundary_values() -> None:
    for epoch in (0, 1, 946_684_800, 2_147_483_647):
        assert (
            normalize_dhan_websocket_timestamp(epoch)
            == datetime.fromtimestamp(epoch, tz=UTC) - IST_UTC_OFFSET
        )


def test_normalization_is_deterministic_and_monotonic() -> None:
    """A one-second increase on the wire must remain exactly a
    one-second increase after correction - the offset is constant, so
    it can never reorder ticks."""
    base = 1_700_000_000
    first = normalize_dhan_websocket_timestamp(base)
    second = normalize_dhan_websocket_timestamp(base + 1)
    assert (second - first).total_seconds() == 1.0
    assert normalize_dhan_websocket_timestamp(base) == first


# --------------------------------------------------------------------
# 2. The decoder applies it - on BOTH packet types
# --------------------------------------------------------------------


def test_ticker_packet_decodes_to_normalized_timestamp() -> None:
    epoch = 1_700_000_000
    packet = decode_packet(_ticker_packet_bytes(ltt_epoch=epoch))
    assert isinstance(packet, DhanTickerPacket)
    assert packet.last_trade_time == normalize_dhan_websocket_timestamp(epoch)


def test_quote_packet_decodes_to_normalized_timestamp() -> None:
    epoch = 1_700_000_000
    packet = decode_packet(_quote_packet_bytes(ltt_epoch=epoch))
    assert isinstance(packet, DhanQuotePacket)
    assert packet.last_trade_time == normalize_dhan_websocket_timestamp(epoch)


def test_both_packet_types_agree_on_the_same_epoch() -> None:
    """There must not be two different corrections - one canonical
    conversion point means identical output for identical input."""
    epoch = 1_700_000_000
    ticker = decode_packet(_ticker_packet_bytes(ltt_epoch=epoch))
    quote = decode_packet(_quote_packet_bytes(ltt_epoch=epoch))
    assert isinstance(ticker, DhanTickerPacket)
    assert isinstance(quote, DhanQuotePacket)
    assert ticker.last_trade_time == quote.last_trade_time


def test_canonical_quote_carries_the_normalized_timestamp() -> None:
    """End-to-end across the provider boundary: raw bytes -> decoder ->
    canonical `Quote`."""
    epoch = 1_700_000_000
    packet = decode_packet(_ticker_packet_bytes(ltt_epoch=epoch))
    assert isinstance(packet, DhanTickerPacket)
    conversion = convert_packet_to_quote(packet, security_id_to_symbol=_SYMBOL_MAP)
    assert conversion.quote is not None
    assert conversion.quote.timestamp == normalize_dhan_websocket_timestamp(epoch)
    assert conversion.quote.timestamp.utcoffset() == timedelta(0)


# --------------------------------------------------------------------
# 3. The 2,154-sample 64.70 regression corpus
# --------------------------------------------------------------------


def test_the_64_70_corpus_reproduces_the_original_anomaly() -> None:
    """Guards the fixture itself: if this ever stops showing ~19,800s,
    the corpus was corrupted and every conclusion below is void."""
    observations = parsed_observations()
    assert len(observations) == 2154
    deltas = [(src - fetched).total_seconds() for _s, src, fetched in observations]
    assert min(deltas) > 19_790
    assert max(deltas) < 19_801
    mean = sum(deltas) / len(deltas)
    assert 19_799 < mean < 19_800


def test_every_64_70_observation_normalizes_to_approximately_its_receipt_time() -> None:
    """Directive question D, over the FULL 2,154-row corpus.

    Applying the same correction the decoder applies must move every
    single observation from ~5h30m in the future to within a couple of
    seconds of when it was actually received."""
    for symbol, source, fetched in parsed_observations():
        corrected = source - IST_UTC_OFFSET
        corrected_delta = (corrected - fetched).total_seconds()
        assert -5.0 < corrected_delta <= 0.0, f"{symbol} corrected delta {corrected_delta}s"


def test_corrected_64_70_deltas_are_network_latency_scale_not_hours() -> None:
    corrected = [
        (source - IST_UTC_OFFSET - fetched).total_seconds()
        for _s, source, fetched in parsed_observations()
    ]
    mean = sum(corrected) / len(corrected)
    # Was +19,799.25s; must now be sub-second-scale and NEGATIVE (a
    # trade is always observed slightly AFTER it happened - a positive
    # mean would mean we had merely moved the anomaly, not fixed it).
    assert -1.0 < mean < 0.0
    assert min(corrected) > -5.0
    assert max(corrected) <= 0.0


def test_no_corrected_64_70_observation_is_in_the_future_at_its_receipt_instant() -> None:
    """The precise property aggregation's guard tests. Zero of 2,154
    may now be future-dated relative to its own receipt time - in
    64.70, all 2,154 were."""
    future_dated = [
        symbol
        for symbol, source, fetched in parsed_observations()
        if (source - IST_UTC_OFFSET) > fetched
    ]
    assert future_dated == []


# --------------------------------------------------------------------
# 4. Aggregation acceptance + bar formation (directive §6)
# --------------------------------------------------------------------


def _quote_at(ts: datetime, price: str) -> Quote:
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        timestamp=ts,
        last_price=Decimal(price),
        source="dhan_websocket",
    )


def test_uncorrected_dhan_timestamp_would_still_be_rejected_as_future() -> None:
    """Proves the aggregation safety check is UNCHANGED and still
    working - the fix is upstream, not a weakening of this guard."""
    as_of = datetime(2026, 8, 25, 6, 55, tzinfo=UTC)
    uncorrected = as_of + IST_UTC_OFFSET  # what 64.70 actually produced
    result = aggregate_quotes_into_bars(
        (_quote_at(uncorrected, "100.0"),),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source=_DATA_SOURCE,
    )
    assert result.bars == ()


def test_corrected_dhan_quotes_are_accepted_and_form_a_bar() -> None:
    """Directive question E - synthetic, frozen time, no wall clock."""
    as_of = datetime(2026, 8, 25, 6, 55, tzinfo=UTC)
    minute = datetime(2026, 8, 25, 6, 52, tzinfo=UTC)
    # Raw provider epochs, IST-labelled exactly as Dhan sends them.
    raw_epochs = [
        int((minute + timedelta(seconds=s) + IST_UTC_OFFSET).timestamp()) for s in (0, 20, 40)
    ]
    quotes = [
        _quote_at(normalize_dhan_websocket_timestamp(e), p)
        for e, p in zip(raw_epochs, ("100.0", "102.0", "101.0"), strict=True)
    ]
    result = aggregate_quotes_into_bars(
        tuple(quotes),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source=_DATA_SOURCE,
    )

    assert len(result.bars) == 1
    bar = result.bars[0]
    assert bar.status is BarStatus.CLOSED
    assert bar.open == Decimal("100.0")
    assert bar.high == Decimal("102.0")
    assert bar.low == Decimal("100.0")
    assert bar.close == Decimal("101.0")


def test_corrected_quotes_in_the_current_minute_reach_forming() -> None:
    minute = datetime(2026, 8, 25, 6, 52, tzinfo=UTC)
    as_of = minute + timedelta(seconds=30)
    raw_epoch = int((minute + IST_UTC_OFFSET).timestamp())
    quotes = [_quote_at(normalize_dhan_websocket_timestamp(raw_epoch), "100.0")]
    result = aggregate_quotes_into_bars(
        tuple(quotes),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source=_DATA_SOURCE,
    )
    assert len(result.bars) == 1
    assert result.bars[0].status is BarStatus.FORMING


def test_full_decode_path_produces_a_bar_from_real_dhan_bytes() -> None:
    """The strongest offline proof available: real, correctly-shaped
    Dhan wire bytes -> decode -> canonical Quote -> aggregation -> bar,
    with no step stubbed out."""
    minute = datetime(2026, 8, 25, 6, 52, tzinfo=UTC)
    as_of = datetime(2026, 8, 25, 6, 55, tzinfo=UTC)
    quotes = []
    for seconds, price in ((0, 100.0), (20, 103.0), (40, 101.5)):
        epoch = int((minute + timedelta(seconds=seconds) + IST_UTC_OFFSET).timestamp())
        packet = decode_packet(_ticker_packet_bytes(ltt_epoch=epoch, ltp=price))
        assert isinstance(packet, DhanTickerPacket)
        conversion = convert_packet_to_quote(packet, security_id_to_symbol=_SYMBOL_MAP)
        assert conversion.quote is not None, "a corrected quote must not be rejected"
        quotes.append(conversion.quote)

    result = aggregate_quotes_into_bars(
        tuple(quotes),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source=_DATA_SOURCE,
    )
    assert len(result.bars) == 1
    assert result.bars[0].status is BarStatus.CLOSED
    assert result.bars[0].high == Decimal("103.0")


# --------------------------------------------------------------------
# 5. Scope containment (directive §3)
# --------------------------------------------------------------------


def test_quote_packet_volume_path_is_unchanged_by_the_timestamp_fix() -> None:
    """64.64's cumulative-volume mapping must survive untouched."""
    packet = decode_packet(_quote_packet_bytes(ltt_epoch=1_700_000_000, volume=123_456))
    assert isinstance(packet, DhanQuotePacket)
    conversion = convert_packet_to_quote(packet, security_id_to_symbol=_SYMBOL_MAP)
    assert conversion.quote is not None
    assert conversion.quote.cumulative_volume == Decimal("123456")


def test_ticker_sourced_quotes_still_carry_no_fabricated_volume() -> None:
    packet = decode_packet(_ticker_packet_bytes(ltt_epoch=1_700_000_000))
    assert isinstance(packet, DhanTickerPacket)
    conversion = convert_packet_to_quote(packet, security_id_to_symbol=_SYMBOL_MAP)
    assert conversion.quote is not None
    assert conversion.quote.cumulative_volume is None


def test_the_offset_constant_is_defined_in_exactly_one_place() -> None:
    """Directive §5: no scattered `timedelta(hours=5, minutes=30)`.
    The literal may appear ONLY in the canonical normalization module."""
    import pathlib

    src_root = pathlib.Path(__file__).resolve().parents[3] / "src"
    offenders = [
        path
        for path in src_root.rglob("*.py")
        if path.name != "timestamp_normalization.py"
        and "hours=5, minutes=30" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
