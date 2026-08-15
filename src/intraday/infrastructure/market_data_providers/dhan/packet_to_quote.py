# File: src/intraday/infrastructure/market_data_providers/dhan/packet_to_quote.py
#
# Checkpoint 54: the bridge Checkpoint 53 explicitly left undone -
# `packet_decoder.py` produces Dhan-shaped typed packets
# (`DhanTickerPacket`/`DhanQuotePacket`); nothing converted those into
# this project's own canonical, provider-neutral `domain.market_data.
# contracts.Quote` (the SAME contract `LiveQuoteRepository`/
# `BarAggregationService` already consume, Checkpoint 23/24A). This
# module is that conversion - the ONE place `SecurityId`/Dhan packet
# shape is translated into the canonical vocabulary, mirroring
# `infrastructure/api/market_data_views.py::_observation_to_quote()`'s
# own established "Dhan-shaped in, canonical `Quote` out" precedent
# exactly, for the WebSocket path instead of the REST path.
#
# Deliberately takes `security_id_to_symbol` as a caller-supplied
# mapping rather than reading `observation_universe()` itself - this
# module stays a pure, side-effect-free function; a future worker
# builds that mapping once (from the SAME `observation_universe()`
# Checkpoint 23 already established) and passes it in, matching this
# project's own "caller supplies inputs" discipline used throughout
# (e.g. `run_position_monitor_tick(current_prices=...)`).
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanQuotePacket,
    DhanTickerPacket,
)

DHAN_WEBSOCKET_SOURCE = "dhan_websocket"


class QuoteConversionRejectionReason(Enum):
    UNKNOWN_SECURITY_ID = "UNKNOWN_SECURITY_ID"
    """The packet's `security_id` has no entry in the caller-supplied
    mapping - this instrument is not part of the configured observation
    universe (or the mapping is stale). NEVER fabricated - a security_id
    this project has no verified symbol for produces no `Quote` at all,
    matching `instruments.py::UnknownObservationSymbolError`'s own
    "refuse to guess" discipline."""
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    """The packet's last-traded-price decoded to zero or negative - the
    domain `Quote` contract requires a strictly positive `last_price`
    (Checkpoint 5); a malformed/zero price must be rejected explicitly,
    never silently coerced into some fallback value."""


@dataclass(frozen=True, slots=True)
class QuoteConversionResult:
    quote: Quote | None
    rejected_reason: QuoteConversionRejectionReason | None

    @property
    def accepted(self) -> bool:
        return self.quote is not None


def convert_packet_to_quote(
    packet: DhanTickerPacket | DhanQuotePacket,
    *,
    security_id_to_symbol: Mapping[int, str],
) -> QuoteConversionResult:
    """Converts ONE decoded Dhan packet into the canonical `Quote`
    contract, or an explicit, typed rejection - never raises, never
    fabricates a `Quote` for an unmapped instrument or an invalid
    price. Works identically for `DhanTickerPacket` and
    `DhanQuotePacket` since both packet types carry a last-traded-price
    and last-trade-time in the SAME shape (`Quote`'s own mandatory
    fields); `DhanQuotePacket`'s additional fields (volume, day OHLC)
    are NOT mapped into `Quote` this checkpoint - `Quote` has no volume
    field (see `domain/market_data/contracts.py`), and day OHLC belongs
    to the bar/aggregation layer, not a point-in-time quote. A future
    checkpoint building the canonical-observation pipeline in full
    (Part 9 of this checkpoint's own broader ask) may need a richer
    contract than `Quote` for that - not attempted here, named
    honestly rather than silently dropped."""
    symbol = security_id_to_symbol.get(packet.header.security_id)
    if symbol is None:
        return QuoteConversionResult(
            quote=None, rejected_reason=QuoteConversionRejectionReason.UNKNOWN_SECURITY_ID
        )

    last_price = Decimal(str(round(packet.last_traded_price, 4)))
    if last_price <= 0:
        return QuoteConversionResult(
            quote=None, rejected_reason=QuoteConversionRejectionReason.NON_POSITIVE_PRICE
        )

    instrument_id = make_instrument_id(Exchange.NSE, symbol)
    quote = Quote(
        instrument_id=instrument_id,
        timestamp=packet.last_trade_time,
        last_price=last_price,
        source=DHAN_WEBSOCKET_SOURCE,
    )
    return QuoteConversionResult(quote=quote, rejected_reason=None)


def build_security_id_to_symbol_map(instruments: tuple[DhanInstrument, ...]) -> dict[int, str]:
    """Convenience builder for the caller-supplied mapping
    `convert_packet_to_quote()` needs, from the SAME `DhanInstrument`
    tuple `instruments.py::observation_universe()` already produces -
    kept as a tiny, separate, pure function rather than importing
    `observation_universe()` (an environment-reading function) directly
    into this otherwise side-effect-free module."""
    return {instrument.security_id: instrument.symbol for instrument in instruments}
