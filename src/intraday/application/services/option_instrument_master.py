# File: src/intraday/application/services/option_instrument_master.py
#
# Checkpoint 64.77: the option-side of the instrument master.
#
# Shaped deliberately as a SIBLING of
# `application/services/instrument_master.py`, not a replacement for it:
# same provider-Protocol + frozen-dataclass-service pattern, same
# dependency-inversion discipline (the Protocol lives here, the Dhan
# implementation depends inward on it). The equity instrument master is
# untouched by this checkpoint - equities remain fully supported as
# underlying/reference instruments.
#
# PERSISTENCE: none, on purpose. The equity instrument master is loaded
# and cached from the provider's CSV rather than persisted to a table
# (see `dhan/instrument_master.py`'s process-local TTL cache), and
# Phase 13 of this checkpoint says to follow whatever the equity master
# already does rather than add a table because one feels convenient.
# So no `OptionContract` table, no migration, and nothing to keep in
# sync with the provider's own current-state file. The consequence -
# that this is PRESENT-STATE data with no history - is recorded in
# `historical_snapshot_requirement()` below and in the architecture doc.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from intraday.domain.instrument.options import (
    OptionContract,
    OptionContractId,
    OptionContractIdentityError,
    OptionInstrumentRecord,
    OptionType,
    make_option_contract_id,
)
from intraday.domain.shared_kernel.contracts import Exchange


class DuplicateOptionContractError(OptionContractIdentityError):
    """Raised when one master load yields two records with the SAME
    canonical contract identity but genuinely different content.

    An exactly-repeated row is idempotent and accepted (providers do
    republish rows); a CONFLICTING duplicate is rejected, because
    silently keeping either one would make the resulting universe depend
    on CSV row order."""


class OptionInstrumentMasterProvider(Protocol):
    def list_option_contracts(self, exchange: Exchange) -> tuple[OptionInstrumentRecord, ...]:
        """Every option contract the provider currently publishes for
        `exchange` - INCLUDING index options, which the provider layer
        must not silently drop. Excluding them is a product-scope
        decision made here in the service, so that an OPTIDX row stays
        recognisable rather than becoming indistinguishable from a
        parse failure."""
        ...


@dataclass(frozen=True, slots=True)
class OptionInstrumentMasterService:
    """The Phase 5 query surface over the option instrument master.

    Loads once per instance and indexes in memory. A full NSE stock
    option universe is on the order of 10^4 contracts - small enough
    that dict indexes beat any query engine, and large enough that a
    linear scan per lookup inside a scanner loop would not be
    acceptable (the same "avoid obviously inefficient" discipline the
    equity master's TTL cache follows)."""

    provider: OptionInstrumentMasterProvider
    exchange: Exchange = Exchange.NSE

    # --- loading ------------------------------------------------------
    def _stock_option_records(self) -> tuple[OptionInstrumentRecord, ...]:
        """The ACTIVE universe: stock options only.

        Index options are filtered here - not rejected - because this is
        a sweep over a mixed master, where an OPTIDX row is expected and
        correct data, merely out of scope. `require_stock_option()`
        handles the other case (a specific out-of-scope contract handed
        to a selector), where raising is right."""
        seen: dict[OptionContractId, OptionInstrumentRecord] = {}
        for record in self.provider.list_option_contracts(self.exchange):
            if not record.contract.is_stock_option:
                continue
            existing = seen.get(record.contract_id)
            if existing is not None:
                if existing == record:
                    continue  # idempotent republish of an identical row
                raise DuplicateOptionContractError(
                    f"conflicting duplicate contract identity {record.contract_id}: "
                    f"{existing.provider_identity} vs {record.provider_identity}"
                )
            seen[record.contract_id] = record
        return tuple(
            seen[key]
            for key in sorted(
                seen,
                key=lambda cid: (
                    seen[cid].contract.underlying_symbol,
                    seen[cid].contract.expiry,
                    seen[cid].contract.strike,
                    seen[cid].contract.option_type.value,
                ),
            )
        )

    def stock_option_universe(self) -> tuple[OptionInstrumentRecord, ...]:
        """Every ACTIVE stock-option contract, deterministically ordered
        by (underlying, expiry, strike, CE/PE)."""
        return self._stock_option_records()

    # --- Phase 5 queries ----------------------------------------------
    def contracts_for_underlying(
        self, underlying_symbol: str, *, expiry: date | None = None
    ) -> tuple[OptionInstrumentRecord, ...]:
        """All contracts for underlying X - at expiry Y when `expiry` is
        given, across every available expiry when it is not."""
        wanted = underlying_symbol.strip().upper()
        return tuple(
            record
            for record in self._stock_option_records()
            if record.contract.underlying_symbol == wanted
            and (expiry is None or record.contract.expiry == expiry)
        )

    def contracts_for_expiry(
        self, expiry: date, *, option_type: OptionType | None = None
    ) -> tuple[OptionInstrumentRecord, ...]:
        """All contracts expiring on `expiry`, optionally narrowed to
        CE only or PE only."""
        return tuple(
            record
            for record in self._stock_option_records()
            if record.contract.expiry == expiry
            and (option_type is None or record.contract.option_type is option_type)
        )

    def available_expiries(self, underlying_symbol: str) -> tuple[date, ...]:
        """The expiries actually PRESENT in the master for `underlying`,
        ascending.

        Phase 6: these are observed values only. This layer never
        computes "last Thursday of the month" or any other weekly/
        monthly expiry rule - a guessed expiry that the exchange has
        shifted for a holiday would address a contract that does not
        exist, and a derived calendar is exactly the kind of provider
        fact this project refuses to invent."""
        return tuple(
            sorted(
                {
                    record.contract.expiry
                    for record in self.contracts_for_underlying(underlying_symbol)
                }
            )
        )

    def strikes_for(self, underlying_symbol: str, *, expiry: date) -> tuple[Decimal, ...]:
        """Every distinct strike listed for (underlying, expiry),
        ascending."""
        return tuple(
            sorted(
                {
                    record.contract.strike
                    for record in self.contracts_for_underlying(underlying_symbol, expiry=expiry)
                }
            )
        )

    def underlyings(self) -> tuple[str, ...]:
        """Every underlying with at least one listed stock option."""
        return tuple(
            sorted({record.contract.underlying_symbol for record in self._stock_option_records()})
        )

    def find_contract(
        self,
        *,
        underlying_symbol: str,
        expiry: date,
        strike: Decimal,
        option_type: OptionType,
    ) -> OptionInstrumentRecord | None:
        """The exact contract for (underlying, expiry, strike, CE/PE),
        or `None` if it is not listed. Strike matching is by canonical
        identity, so `Decimal("2500")` and `Decimal("2500.00")` resolve
        to the same contract."""
        if not isinstance(strike, Decimal):
            raise OptionContractIdentityError(
                "find_contract(strike=...) must be a Decimal, never a float"
            )
        wanted = make_option_contract_id(
            exchange=self.exchange,
            underlying_symbol=underlying_symbol,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
        for record in self._stock_option_records():
            if record.contract_id == wanted:
                return record
        return None

    def provider_security_id_for(self, contract: OptionContract) -> int | None:
        """The provider-native `security_id` for a canonical contract -
        the one bridge a live/REST adapter needs, and the reason
        provider identity is preserved rather than discarded at the
        mapping boundary."""
        for record in self._stock_option_records():
            if record.contract_id == contract.contract_id:
                return record.provider_identity.security_id
        return None


def historical_snapshot_requirement() -> str:
    """Phase 7, recorded in code rather than only in prose because it is
    a correctness constraint on any future historical option research.

    Not implemented this checkpoint: adding a snapshot store would mean
    adding the persistence layer the equity instrument master
    deliberately does not have, which Phase 13 rules out."""
    return (
        "The option instrument master is PRESENT-STATE provider data. Whether Dhan's "
        "scrip master retains EXPIRED contracts is UNVERIFIED (64.76 open question 3). "
        "Deterministic historical reconstruction of an option universe therefore "
        "requires dated, archived instrument-master snapshots captured while each "
        "contract was still listed. Canonical OptionContract identity is stable and "
        "provider-independent by construction, so such snapshots can be joined by "
        "contract_id across time even if a provider reassigns security_ids."
    )


__all__ = [
    "DuplicateOptionContractError",
    "OptionInstrumentMasterProvider",
    "OptionInstrumentMasterService",
    "historical_snapshot_requirement",
]
