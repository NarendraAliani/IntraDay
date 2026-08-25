# File: src/intraday/application/repositories/option_market_data.py
#
# Checkpoint 64.78: repository Protocols for OPTION observations,
# mirroring `live_market_data.py`'s own precedent exactly - a dedicated
# module, Protocols only, dealing solely in canonical domain contracts
# (`OptionQuote`/`OIObservation`) and never in a Dhan-shaped type.
#
# The application layer, and these Protocols, have ZERO knowledge of
# Dhan's security_id/exchange-segment/packet vocabulary. `provider` and
# `provider_security_id` travel INSIDE the domain observations as
# provenance (see `option_observations.py`), which is not the same thing
# as this layer knowing what a Dhan segment code means.
#
# Two Protocols rather than one, for the same reason there are two
# contracts and two tables: a quote observation and an OI observation
# arrive in separate packets on separate cadences, and a single
# `save_all()` taking both would force a caller to hold one back waiting
# for the other.
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from intraday.domain.market_data.option_observations import OIObservation, OptionQuote


class OptionQuoteRepository(Protocol):
    """Persists and retrieves observed `OptionQuote`s. APPEND-ONLY: a
    `save_all()` never updates or replaces an existing row, because two
    genuine prints can share a one-second provider timestamp and
    deduplicating them would destroy real market events (see
    `OptionQuoteObservation`'s own model docstring)."""

    def save_all(self, quotes: tuple[OptionQuote, ...], *, fetched_at: datetime) -> None:
        """`fetched_at` is OUR receive clock, supplied by the caller -
        the same separation `LiveQuoteRepository.save_all()` draws, so
        the provider's own instant is never overwritten by ours."""
        ...

    def get_observations(
        self, *, trading_date: date, contract_id: str | None = None
    ) -> tuple[OptionQuote, ...]:
        """Every observation for one canonical trading day, optionally
        narrowed to a single contract. Keyed on `trading_date` rather
        than a timestamp range because the trading DAY is the unit a
        future option archive layer works in (64.73's model)."""
        ...


class OIObservationRepository(Protocol):
    """Persists and retrieves `OIObservation`s. Append-only, as above.

    Note what is absent: no `get_oi_change()`. OI change is DERIVED from
    this series by a consumer against a declared baseline - Dhan never
    publishes it (64.76: VERIFIED ABSENT) - and a repository that
    returned one would be presenting a computation as stored data."""

    def save_all(
        self, observations: tuple[OIObservation, ...], *, fetched_at: datetime
    ) -> None: ...

    def get_observations(
        self, *, trading_date: date, contract_id: str | None = None
    ) -> tuple[OIObservation, ...]: ...


__all__ = ["OIObservationRepository", "OptionQuoteRepository"]
