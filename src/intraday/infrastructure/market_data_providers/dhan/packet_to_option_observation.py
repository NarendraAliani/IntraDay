# File: src/intraday/infrastructure/market_data_providers/dhan/packet_to_option_observation.py
#
# Checkpoint 64.78: the OPTION-side sibling of `packet_to_quote.py` -
# "provider packet in, canonical provider-neutral observation out", with
# every Dhan-specific detail staying here in the Dhan infrastructure
# package and none of it leaking into the domain.
#
# It is a SIBLING, not a replacement and not a fork: `packet_to_quote.py`
# is untouched by this checkpoint and remains the ONE path an NSE_EQ
# packet takes. The equity path's behaviour is unchanged, byte for byte.
#
# WHY A SECOND MAPPER RATHER THAN GENERALISING THE FIRST. The two differ
# in their IDENTITY resolution, not in their arithmetic. The equity
# mapper resolves `security_id -> symbol -> InstrumentId`; the option
# mapper resolves `security_id -> ProviderOptionIdentity ->
# OptionContract`, and produces a different observation type. Forcing one
# function to do both would have required it to know which universe a
# security_id belongs to - which is exactly the ambiguity that makes
# routing bugs mis-attribute an option print to an equity symbol.
#
# THE ONE HARD RULE (this checkpoint's Phase 10): strike, expiry and
# CE/PE are NEVER read out of a packet. A Dhan feed packet carries only
# `(segment, security_id)`; the contract those address is looked up in
# the 64.77 instrument master. If the lookup fails, the observation is
# REJECTED with a typed reason - a contract identity is never fabricated,
# because a fabricated identity would file a real market print against
# the wrong strike, permanently and undetectably.
from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from intraday.domain.instrument.options import OptionInstrumentRecord
from intraday.domain.market_data.option_observations import (
    OIObservation,
    OptionObservationError,
    OptionQuote,
)
from intraday.infrastructure.market_data_providers.dhan.packet_decoder import (
    DhanOpenInterestPacket,
    DhanQuotePacket,
    DhanTickerPacket,
)

DHAN_PROVIDER = "dhan"
"""The provider name stamped onto every option observation's IDENTITY
side (`OptionQuote.provider`). Deliberately distinct from
`DHAN_WEBSOCKET_SOURCE` below, which is the PROVENANCE side (which
transport/packet path produced the row) - one provider can have several
sources (WebSocket now, REST option chain later)."""

DHAN_WEBSOCKET_SOURCE = "dhan_websocket"
"""Reused verbatim from `packet_to_quote.py` rather than redefined with
a new spelling: an option row and an equity row that came off the SAME
WebSocket must carry the SAME provenance string, or `data_source`-keyed
analysis would split one real source into two."""


class OptionObservationRejectionReason(Enum):
    """Every way an option observation can be refused. Typed, never a
    free-text log line, so the worker can COUNT rejections by cause -
    the safe diagnostic this checkpoint's Phase 10 requires in place of
    fabricating identity."""

    UNRESOLVED_SECURITY_ID = "UNRESOLVED_SECURITY_ID"
    """The packet's `security_id` is not in the resolved option universe.
    Either the instrument master is stale, or this packet belongs to some
    other subscription entirely. Never guessed at."""

    INDEX_OPTION_NOT_IN_SCOPE = "INDEX_OPTION_NOT_IN_SCOPE"
    """The security_id resolved to an OPTIDX contract. Index options are
    representable but NOT enabled by the 64.77 product scope, so an
    observation of one is dropped here rather than persisted into a
    universe that is supposed to be stock options only. Structural
    defence-in-depth: the subscription layer should never have asked for
    it in the first place."""

    NON_POSITIVE_PREMIUM = "NON_POSITIVE_PREMIUM"
    """The decoded last-traded premium was zero or negative - not a
    tradable print, and the classic shape of a padding/corrupt frame."""

    NEGATIVE_OPEN_INTEREST = "NEGATIVE_OPEN_INTEREST"
    """The OI packet's int32 decoded negative. Open interest is a
    contract count and cannot be negative, so this is a misparse or a
    corrupt frame, never a market fact worth archiving."""

    INVALID_OBSERVATION = "INVALID_OBSERVATION"
    """The domain contract itself refused the assembled observation
    (`OptionObservationError`). Caught and converted to a rejection so
    that, exactly like `decode_packet()`, no single bad packet can raise
    through and stop a live worker."""


@dataclass(frozen=True, slots=True)
class OptionQuoteConversionResult:
    quote: OptionQuote | None
    rejected_reason: OptionObservationRejectionReason | None

    @property
    def accepted(self) -> bool:
        return self.quote is not None


@dataclass(frozen=True, slots=True)
class OIConversionResult:
    observation: OIObservation | None
    rejected_reason: OptionObservationRejectionReason | None

    @property
    def accepted(self) -> bool:
        return self.observation is not None


def build_security_id_to_option_record_map(
    records: tuple[OptionInstrumentRecord, ...],
) -> dict[int, OptionInstrumentRecord]:
    """The resolution index a live worker builds ONCE from
    `OptionInstrumentMasterService.stock_option_universe()` and then
    passes in, mirroring `build_security_id_to_symbol_map()`'s own
    caller-supplies-inputs discipline exactly - this module performs no
    I/O and reads no environment.

    A provider that ever reused one security_id across two contracts
    would collapse them here, so the LAST record wins deterministically
    only because the master service already rejects conflicting
    duplicates upstream (`DuplicateOptionContractError`)."""
    return {record.provider_identity.security_id: record for record in records}


def _resolve(
    security_id: int,
    security_id_to_option: Mapping[int, OptionInstrumentRecord],
) -> tuple[OptionInstrumentRecord | None, OptionObservationRejectionReason | None]:
    record = security_id_to_option.get(security_id)
    if record is None:
        return None, OptionObservationRejectionReason.UNRESOLVED_SECURITY_ID
    if not record.contract.is_stock_option:
        return None, OptionObservationRejectionReason.INDEX_OPTION_NOT_IN_SCOPE
    return record, None


def _optional_price(value: float) -> Decimal | None:
    """Day-OHLC fields arrive as float32 and are legitimately 0.0 before
    a contract has traded at all today. Zero becomes `None` ("not
    observed") rather than a fabricated price - `OptionQuote` would
    reject a non-positive value anyway, and honest absence is the right
    reading for an untraded strike, which is extremely common in the
    option chain's far wings."""
    if value <= 0:
        return None
    return Decimal(str(round(value, 4)))


def convert_packet_to_option_quote(
    packet: DhanTickerPacket | DhanQuotePacket,
    *,
    security_id_to_option: Mapping[int, OptionInstrumentRecord],
) -> OptionQuoteConversionResult:
    """One decoded Dhan Ticker/Quote packet -> one canonical
    `OptionQuote`, or a typed rejection. Never raises.

    Phase 5: the SAME decoded `DhanQuotePacket` type the equity path
    consumes is accepted here unchanged. Dhan's Quote packet wire format
    is identical for NSE_EQ and NSE_FNO (64.76) - the premium of an
    option is just "the last traded price" of that instrument - so the
    decoder is reused verbatim and only the identity resolution and
    output contract differ. `DhanTickerPacket` is accepted too (it is a
    strict subset: LTP + LTT, no volume, no day OHLC), so a Ticker-mode
    option subscription still produces honest observations with `None`
    where the packet genuinely carries nothing."""
    record, rejection = _resolve(packet.header.security_id, security_id_to_option)
    if record is None:
        return OptionQuoteConversionResult(quote=None, rejected_reason=rejection)

    last_price = Decimal(str(round(packet.last_traded_price, 4)))
    if last_price <= 0:
        return OptionQuoteConversionResult(
            quote=None, rejected_reason=OptionObservationRejectionReason.NON_POSITIVE_PREMIUM
        )

    cumulative_volume: Decimal | None = None
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None
    if isinstance(packet, DhanQuotePacket):
        if packet.volume >= 0:
            cumulative_volume = Decimal(str(packet.volume))
        open_price = _optional_price(packet.day_open)
        high_price = _optional_price(packet.day_high)
        low_price = _optional_price(packet.day_low)
        previous_close = _optional_price(packet.day_close)

    try:
        quote = OptionQuote(
            contract=record.contract,
            provider=record.provider_identity.provider,
            provider_security_id=record.provider_identity.security_id,
            timestamp=packet.last_trade_time,
            last_price=last_price,
            data_source=DHAN_WEBSOCKET_SOURCE,
            cumulative_volume=cumulative_volume,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            previous_close=previous_close,
        )
    except OptionObservationError:
        return OptionQuoteConversionResult(
            quote=None, rejected_reason=OptionObservationRejectionReason.INVALID_OBSERVATION
        )
    return OptionQuoteConversionResult(quote=quote, rejected_reason=None)


def convert_packet_to_oi_observation(
    packet: DhanOpenInterestPacket,
    *,
    security_id_to_option: Mapping[int, OptionInstrumentRecord],
    observed_at: _dt.datetime,
) -> OIConversionResult:
    """One decoded Dhan OI packet (code 5) -> one canonical
    `OIObservation`, or a typed rejection. Never raises.

    `observed_at` is REQUIRED from the caller and never defaulted to
    `datetime.now()` inside this module: the OI packet carries no
    timestamp of its own (12 bytes: header + int32), so the instant is
    necessarily OUR receipt clock, and making the caller supply it keeps
    this function pure and deterministically testable - the same
    discipline `run_position_monitor_tick(current_prices=...)` and
    `save_all(fetched_at=...)` already follow."""
    record, rejection = _resolve(packet.header.security_id, security_id_to_option)
    if record is None:
        return OIConversionResult(observation=None, rejected_reason=rejection)

    if packet.open_interest < 0:
        return OIConversionResult(
            observation=None,
            rejected_reason=OptionObservationRejectionReason.NEGATIVE_OPEN_INTEREST,
        )

    try:
        observation = OIObservation(
            contract=record.contract,
            provider=record.provider_identity.provider,
            provider_security_id=record.provider_identity.security_id,
            observed_at=observed_at,
            open_interest=packet.open_interest,
            data_source=DHAN_WEBSOCKET_SOURCE,
        )
    except OptionObservationError:
        return OIConversionResult(
            observation=None,
            rejected_reason=OptionObservationRejectionReason.INVALID_OBSERVATION,
        )
    return OIConversionResult(observation=observation, rejected_reason=None)


__all__ = [
    "DHAN_PROVIDER",
    "DHAN_WEBSOCKET_SOURCE",
    "OIConversionResult",
    "OptionObservationRejectionReason",
    "OptionQuoteConversionResult",
    "build_security_id_to_option_record_map",
    "convert_packet_to_oi_observation",
    "convert_packet_to_option_quote",
]
