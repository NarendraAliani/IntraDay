# File: src/intraday/domain/instrument/options.py
#
# Checkpoint 64.77: the canonical, provider-independent IDENTITY of an
# NSE stock-option contract.
#
# PRODUCT SCOPE (resolved at this checkpoint, superseding the earlier
# "permanently Indian cash equities only" reading of Rule 2):
#
#   PLATFORM            Indian NSE intraday trading platform
#   PRIMARY INSTRUMENT  NSE STOCK OPTIONS (OPTSTK, NSE_FNO segment)
#   SUPPORTING          NSE CASH EQUITIES - retained in full, now also
#                       serving as underlying/reference instruments
#   NOT ENABLED         NSE INDEX OPTIONS (OPTIDX), BSE OPTIONS, BSE
#                       EQUITIES
#
# Index options are deliberately REPRESENTABLE but NOT ACTIVE: an
# OPTIDX row must be parseable (so it can be recognised and excluded on
# purpose rather than misread as a stock option), while every
# stock-option selector rejects it. "Not enabled" enforced structurally
# beats "not enabled" enforced by comment.
#
# WHAT THIS MODULE IS NOT. This is an IDENTITY contract, not an
# observation contract. Open interest, implied volatility, Greeks,
# bid/ask, premium and chain snapshots are OBSERVATIONS of a contract,
# not properties of its identity, and none of them appears here. They
# are deferred to a future checkpoint that adds an observation layer
# (`OptionQuote`/`OptionBar`/`OIObservation`/`OptionChainSnapshot`)
# alongside the existing equity `Quote`/`Bar` rather than bolting
# derivative-only nullable fields onto the contracts backtest, paper and
# live all share for equities (see 64.76's architectural finding in
# docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md).
#
# PROVIDER INDEPENDENCE. Dhan's `security_id` is NOT the identity. The
# natural key is (exchange, underlying, expiry, strike, option_type) -
# facts about the contract as the exchange defines it, true regardless
# of which broker is quoting it. Provider-native identifiers live in a
# SEPARATE value object (`ProviderOptionIdentity`) so a second provider
# can be added later without any contract identity changing.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import NewType

from intraday.domain.shared_kernel.contracts import Exchange

OptionContractId = NewType("OptionContractId", str)


class OptionContractIdentityError(ValueError):
    """Raised when a proposed option identity is not a valid contract.

    Deliberately a hard failure: an invalid strike/expiry/option type is
    never silently coerced to a plausible-looking value, because a
    silently-coerced contract identity would mis-attribute real market
    observations to the wrong strike."""


class OptionType(enum.Enum):
    """Explicit call/put vocabulary, using the exchange's own CE/PE
    spelling (which is also what Dhan's `SEM_OPTION_TYPE` carries), so
    no translation table sits between the scrip master and the domain."""

    CE = "CE"
    PE = "PE"


class DerivativeSegment(enum.Enum):
    """The exchange SEGMENT an option trades in.

    Kept separate from `Exchange` on purpose. `Exchange` answers "which
    exchange" (NSE/BSE) and is shared by equities and options alike;
    this answers "which segment of it". Adding an `NSE_FNO` member to
    `Exchange` itself would have made every existing equity call site
    that switches on `Exchange` silently incomplete."""

    NSE_FNO = "NSE_FNO"


class OptionUnderlyingClass(enum.Enum):
    """Whether the underlying is a single stock or an index.

    This is what keeps OPTIDX recognisable-but-inactive. It mirrors
    Dhan's `SEM_EXCH_INSTRUMENT_TYPE` values OPTSTK/OPTIDX, but is
    stated in domain terms rather than provider terms."""

    STOCK = "STOCK"  # OPTSTK - the active universe
    INDEX = "INDEX"  # OPTIDX - representable, never active (product scope)


@dataclass(frozen=True, slots=True)
class OptionContract:
    """Canonical identity of one exchange-listed option contract.

    Natural key: (exchange, underlying_symbol, expiry, strike,
    option_type). `lot_size`/`tick_size` are contract SPECIFICATION
    (exchange-published, part of what the contract IS) rather than
    identity, so they are carried but excluded from the key - two rows
    describing the same strike with different lot sizes are the same
    contract with a revised spec, not two contracts."""

    exchange: Exchange
    segment: DerivativeSegment
    underlying_symbol: str
    underlying_class: OptionUnderlyingClass
    expiry: date
    strike: Decimal
    option_type: OptionType
    lot_size: int
    tick_size: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise OptionContractIdentityError("OptionContract.exchange must be an Exchange")
        if self.exchange is not Exchange.NSE:
            # BSE derivatives are explicitly not enabled by the 64.77
            # product scope; refuse rather than half-support them.
            raise OptionContractIdentityError(
                f"only NSE options are in product scope, got {self.exchange.value}"
            )
        if not isinstance(self.segment, DerivativeSegment):
            raise OptionContractIdentityError(
                "OptionContract.segment must be a DerivativeSegment (options do not "
                "trade in the cash segment)"
            )
        if not isinstance(self.option_type, OptionType):
            raise OptionContractIdentityError(
                "OptionContract.option_type must be an OptionType (CE/PE), not a raw string"
            )
        if not isinstance(self.underlying_class, OptionUnderlyingClass):
            raise OptionContractIdentityError(
                "OptionContract.underlying_class must be an OptionUnderlyingClass"
            )
        if not self.underlying_symbol or not self.underlying_symbol.strip():
            raise OptionContractIdentityError("OptionContract.underlying_symbol must be non-empty")
        if self.underlying_symbol != self.underlying_symbol.strip().upper():
            raise OptionContractIdentityError(
                "OptionContract.underlying_symbol must be normalised (stripped, upper-case) "
                f"- got {self.underlying_symbol!r}"
            )
        # `bool` is a subclass of `int`; `datetime` is a subclass of `date`.
        # Both would pass a naive isinstance check and both would be wrong.
        if type(self.expiry) is not date:
            raise OptionContractIdentityError(
                "OptionContract.expiry must be a datetime.date - an option expires on a "
                "trading DAY, and a datetime here would make two spellings of the same "
                f"expiry compare unequal (got {type(self.expiry).__name__})"
            )
        if not isinstance(self.strike, Decimal):
            raise OptionContractIdentityError(
                "OptionContract.strike must be a Decimal, never a float - strike is an "
                "exact exchange-published price"
            )
        if self.strike <= 0:
            raise OptionContractIdentityError(
                f"OptionContract.strike must be positive, got {self.strike}"
            )
        if not self.strike.is_finite():
            raise OptionContractIdentityError("OptionContract.strike must be a finite Decimal")
        if type(self.lot_size) is not int or self.lot_size <= 0:
            raise OptionContractIdentityError(
                f"OptionContract.lot_size must be a positive int, got {self.lot_size!r}"
            )
        if not isinstance(self.tick_size, Decimal):
            raise OptionContractIdentityError(
                "OptionContract.tick_size must be a Decimal, never a float"
            )
        if self.tick_size <= 0 or not self.tick_size.is_finite():
            raise OptionContractIdentityError(
                f"OptionContract.tick_size must be a positive finite Decimal, got {self.tick_size}"
            )

    @property
    def contract_id(self) -> OptionContractId:
        return make_option_contract_id(
            exchange=self.exchange,
            underlying_symbol=self.underlying_symbol,
            expiry=self.expiry,
            strike=self.strike,
            option_type=self.option_type,
        )

    @property
    def is_stock_option(self) -> bool:
        """The single structural gate for "is this in the ACTIVE trading
        universe?" - mirrors `Instrument.is_tradable`'s role for
        equities. Index options answer False by construction, so the
        product-scope exclusion cannot be forgotten at a call site."""
        return self.underlying_class is OptionUnderlyingClass.STOCK


def normalise_strike(strike: Decimal) -> str:
    """Canonical strike SPELLING for identity purposes.

    `Decimal("2500")`, `Decimal("2500.0")` and `Decimal("2500.00")` are
    numerically equal but have different `str()` forms, so using `str()`
    directly would mint three different identities for one strike. This
    normalises to the shortest exact representation."""
    normalised = strike.normalize()
    # `.normalize()` renders large round values in exponent form
    # (Decimal("2500") -> "2.5E+3"); expand that back to plain digits.
    sign, digits, exponent = normalised.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalised = normalised.quantize(Decimal(1))
    return f"{normalised:f}"


def make_option_contract_id(
    *,
    exchange: Exchange,
    underlying_symbol: str,
    expiry: date,
    strike: Decimal,
    option_type: OptionType,
) -> OptionContractId:
    """Deterministic canonical identity derivation.

    Mirrors `make_instrument_id`'s contract for equities: the same
    exchange/underlying/expiry/strike/type always yields the same string
    regardless of which adapter or checkpoint constructs it, and no
    broker token participates. This determinism is what makes historical
    identity stable across instrument-master refreshes - a contract
    keeps its identity even if a provider reassigns its security_id."""
    return OptionContractId(
        f"{exchange.value}:FNO:{underlying_symbol.strip().upper()}"
        f":{expiry.isoformat()}:{normalise_strike(strike)}:{option_type.value}"
    )


@dataclass(frozen=True, slots=True)
class ProviderOptionIdentity:
    """PROVIDER-NATIVE identity, held strictly beside the canonical one.

    Dhan's Market Quote/WebSocket/Option Chain APIs address instruments
    by `security_id`, never by strike and expiry, so the mapping must be
    preserved - but it must not BE the identity, or the domain could
    never survive a second data provider (or a provider reassigning an
    id). Keeping it in its own value object makes that separation
    structural."""

    provider: str
    security_id: int
    trading_symbol: str
    exchange_segment: str
    underlying_security_id: int | None = None

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise OptionContractIdentityError("ProviderOptionIdentity.provider must be non-empty")
        if type(self.security_id) is not int or self.security_id <= 0:
            raise OptionContractIdentityError(
                "ProviderOptionIdentity.security_id must be a positive int - refusing to "
                f"carry an unaddressable contract (got {self.security_id!r})"
            )
        if not self.trading_symbol or not self.trading_symbol.strip():
            raise OptionContractIdentityError(
                "ProviderOptionIdentity.trading_symbol must be non-empty"
            )
        if not self.exchange_segment or not self.exchange_segment.strip():
            raise OptionContractIdentityError(
                "ProviderOptionIdentity.exchange_segment must be non-empty"
            )
        if self.underlying_security_id is not None and (
            type(self.underlying_security_id) is not int or self.underlying_security_id <= 0
        ):
            raise OptionContractIdentityError(
                "ProviderOptionIdentity.underlying_security_id, when present, must be a "
                "positive int"
            )


@dataclass(frozen=True, slots=True)
class OptionInstrumentRecord:
    """One instrument-master entry: canonical identity + the provider
    identity it was sourced through.

    This pairing - not the contract alone - is what an instrument-master
    query returns, because callers almost always need both ("which
    strike is this?" AND "what do I send Dhan to subscribe to it?")."""

    contract: OptionContract
    provider_identity: ProviderOptionIdentity

    @property
    def contract_id(self) -> OptionContractId:
        return self.contract.contract_id


def require_stock_option(contract: OptionContract) -> OptionContract:
    """Guard for every stock-option-only entry point.

    Raises rather than filtering, because a caller that hands an OPTIDX
    contract to a stock-option selector has a bug that silence would
    hide - filtering is correct only when SWEEPING a mixed master (see
    the instrument-master service), never when a specific contract was
    named."""
    if not contract.is_stock_option:
        raise OptionContractIdentityError(
            f"{contract.contract_id} is an INDEX option (OPTIDX); index options are "
            "recognised but not enabled by the current product scope - the active "
            "universe is NSE stock options (OPTSTK) only"
        )
    return contract


__all__ = [
    "DerivativeSegment",
    "OptionContract",
    "OptionContractId",
    "OptionContractIdentityError",
    "OptionInstrumentRecord",
    "OptionType",
    "OptionUnderlyingClass",
    "ProviderOptionIdentity",
    "make_option_contract_id",
    "normalise_strike",
    "require_stock_option",
]
