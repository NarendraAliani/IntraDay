# File: src/intraday/domain/market_data/option_observations.py
#
# Checkpoint 64.78: the OBSERVATION layer for options - the counterpart
# 64.77 explicitly deferred when it built option IDENTITY
# (`domain/instrument/options.py`) and said, in its own module docstring:
# "Open interest, implied volatility, Greeks, bid/ask, premium ... are
# OBSERVATIONS of a contract, not properties of its identity ... deferred
# to a future checkpoint that adds an observation layer".
#
# TWO contracts, deliberately not one:
#
#   OptionQuote    - a point-in-time PRICE observation of one contract.
#                    Structurally the option-side sibling of the equity
#                    `Quote` in `contracts.py`, carrying the same
#                    vocabulary (last_price/bid/ask/cumulative_volume/
#                    source) over an `OptionContract` identity instead of
#                    an `InstrumentId`.
#   OIObservation  - a point-in-time OPEN-INTEREST observation.
#
# WHY OI IS NOT A FIELD ON OptionQuote. Dhan does not deliver them
# together: the price fields arrive in the Quote packet (feed response
# code 4) and open interest arrives in a SEPARATE OI packet (code 5, a
# 12-byte packet - 64.76, VERIFIED). They have independent arrival
# instants and either can arrive without the other. An `open_interest:
# int | None` on `OptionQuote` would therefore be `None` on every single
# quote-packet-sourced row, and "no OI field in this packet" would be
# indistinguishable from "OI genuinely unknown". Two observation types
# keep both facts honest, and match 64.76's own recommendation ("a
# separate observation type for the fields `Quote` genuinely lacks ...
# rather than bolting five optional nullable columns onto the equity
# contract every provider shares").
#
# EXPLICITLY NOT HERE (deferred, per this checkpoint's directive):
# implied volatility, Greeks, `OptionChainSnapshot`, `OptionBar`. They
# are REST-option-chain-sourced (IV/Greeks are LIVE-ONLY provider
# values, 64.76) and need a snapshot/aggregation layer this checkpoint
# does not build. OI CHANGE is likewise absent by design - Dhan never
# publishes it (64.76: "VERIFIED ABSENT"), so it is DERIVED later from
# this project's own stored OI series, exactly as per-bar volume is
# derived from consecutive cumulative-volume readings.
#
# ON `fetched_at`. Not a field here, on purpose. The equity `Quote`
# does not carry one either: the local receive clock is stamped at the
# single persistence write boundary
# (`DjangoLiveQuoteRepository.save_all(fetched_at=...)`), because it is
# a fact about OUR ingestion, not about the market observation. The
# option repositories follow that same pattern rather than inventing a
# second convention.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.instrument.options import (
    OptionContract,
    OptionContractId,
)
from intraday.domain.market_data.contracts import MarketDataQuality
from intraday.domain.shared_kernel.contracts import ensure_utc


class OptionObservationError(ValueError):
    """Raised when a proposed option observation is not internally
    coherent (negative premium, crossed bid/ask, naive timestamp).

    A hard failure, matching `OptionContractIdentityError`'s discipline:
    a silently-coerced observation would enter the historical record as
    though the market had really printed it."""


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """A point-in-time premium observation of ONE option contract.

    Identity is the canonical `OptionContract` (never the provider's
    security_id): `provider`/`provider_security_id` are carried BESIDE
    it as provenance, so the observation stays joinable to the provider
    that produced it without the provider's identifier ever becoming the
    thing that identifies the contract. This mirrors 64.77's
    `OptionContract` / `ProviderOptionIdentity` separation exactly.

    `last_price` is the OPTION PREMIUM. Like the equity `Quote` it must
    be strictly positive - a zero premium is not a tradable print, and
    an all-zero packet body is the classic shape of a malformed or
    padding frame.

    Day OHLC is carried as OPTIONAL context (`open_price`/`high_price`/
    `low_price`/`previous_close`), unlike the equity `Quote`, because
    Dhan's Quote packet genuinely delivers day OHLC in the same packet
    as the premium and dropping it would lose real, unrecoverable
    intraday information. `previous_close` is named for what Dhan's
    field actually IS (the prior session's close) rather than the
    ambiguous `close`."""

    contract: OptionContract
    provider: str
    provider_security_id: int
    timestamp: datetime
    """The PROVIDER's own observation instant (last trade time), UTC -
    never our receive clock."""
    last_price: Decimal
    data_source: str = ""
    """Provenance, verbatim (e.g. `"dhan_websocket"`) - never defaulted
    to a provider name. Mirrors `Quote.source` / 64.75."""
    cumulative_volume: Decimal | None = None
    """Provider's day-to-date traded volume, when supplied. NEVER a
    per-tick or per-bar volume - any per-interval volume is DERIVED by
    differencing consecutive readings, as the equity path already does."""
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_quantity: Decimal | None = None
    ask_quantity: Decimal | None = None
    quality: MarketDataQuality = MarketDataQuality.OK

    def __post_init__(self) -> None:
        if not isinstance(self.contract, OptionContract):
            raise OptionObservationError("OptionQuote.contract must be an OptionContract")
        _require_provider(self.provider, self.provider_security_id, "OptionQuote")
        ensure_utc(self.timestamp, field_name="OptionQuote.timestamp")
        if not isinstance(self.last_price, Decimal):
            raise OptionObservationError("OptionQuote.last_price must be a Decimal, never a float")
        if self.last_price <= 0:
            raise OptionObservationError(
                f"OptionQuote.last_price (option premium) must be positive, got {self.last_price}"
            )
        for name, value in (
            ("open_price", self.open_price),
            ("high_price", self.high_price),
            ("low_price", self.low_price),
            ("previous_close", self.previous_close),
            ("bid", self.bid),
            ("ask", self.ask),
        ):
            if value is None:
                continue
            if not isinstance(value, Decimal):
                raise OptionObservationError(f"OptionQuote.{name} must be a Decimal when provided")
            if value <= 0:
                raise OptionObservationError(
                    f"OptionQuote.{name} must be positive when provided, got {value}"
                )
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise OptionObservationError("OptionQuote.bid must not exceed OptionQuote.ask")
        for name, value in (
            ("cumulative_volume", self.cumulative_volume),
            ("bid_quantity", self.bid_quantity),
            ("ask_quantity", self.ask_quantity),
        ):
            if value is not None and value < 0:
                raise OptionObservationError(
                    f"OptionQuote.{name} must not be negative when provided, got {value}"
                )

    @property
    def contract_id(self) -> OptionContractId:
        return self.contract.contract_id


@dataclass(frozen=True, slots=True)
class OIObservation:
    """A point-in-time OPEN-INTEREST observation of one option contract.

    Separate from `OptionQuote` because Dhan delivers it in its own
    packet type with its own arrival instant (see the module docstring).

    `open_interest` is a CONTRACT COUNT, not a price, and is stored as
    an `int` because that is exactly what the wire carries (documented
    int32). Zero is legitimate and meaningful (a listed strike with no
    open positions) so it is accepted; NEGATIVE open interest is
    physically impossible and is rejected here rather than archived - a
    negative int32 in this position means the packet was misparsed or
    corrupt, never that the market printed it.

    `observed_at` is deliberately named differently from
    `OptionQuote.timestamp`: the OI packet carries NO timestamp field of
    its own (its 12-byte layout is header + int32 OI, 64.76), so this
    value is stamped by the ingesting side at receipt. Naming it
    `timestamp` would have implied a provider-supplied instant that does
    not exist."""

    contract: OptionContract
    provider: str
    provider_security_id: int
    observed_at: datetime
    open_interest: int
    data_source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.contract, OptionContract):
            raise OptionObservationError("OIObservation.contract must be an OptionContract")
        _require_provider(self.provider, self.provider_security_id, "OIObservation")
        ensure_utc(self.observed_at, field_name="OIObservation.observed_at")
        # `bool` is a subclass of `int` and would otherwise pass.
        if type(self.open_interest) is not int:
            raise OptionObservationError(
                "OIObservation.open_interest must be an int (a contract count), got "
                f"{type(self.open_interest).__name__}"
            )
        if self.open_interest < 0:
            raise OptionObservationError(
                "OIObservation.open_interest must not be negative - a negative int32 in "
                f"this position indicates a misparsed packet (got {self.open_interest})"
            )

    @property
    def contract_id(self) -> OptionContractId:
        return self.contract.contract_id


def _require_provider(provider: str, security_id: int, owner: str) -> None:
    if not provider or not provider.strip():
        raise OptionObservationError(f"{owner}.provider must be non-empty")
    if type(security_id) is not int or security_id <= 0:
        raise OptionObservationError(
            f"{owner}.provider_security_id must be a positive int - an observation that "
            f"cannot be traced back to the addressed instrument is not archivable "
            f"(got {security_id!r})"
        )


__all__ = [
    "OIObservation",
    "OptionObservationError",
    "OptionQuote",
]
