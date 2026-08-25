# File: src/intraday/infrastructure/persistence/option_market_data_repositories.py
#
# Checkpoint 64.78: Django ORM implementations of the option-observation
# repository Protocols (`application/repositories/option_market_data.py`).
#
# Shaped as a direct sibling of `live_market_data_repositories.py`: the
# ONE place the canonical `OptionQuote`/`OIObservation` contracts are
# converted to and from Django models, `bulk_create` for append-only
# writes (never `update_or_create` - see the models' own docstrings on
# why an option observation table must NOT be keyed by timestamp), and
# `trading_date`/`fetched_at` stamped at this single write boundary
# rather than by every caller.
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from intraday.domain.instrument.options import (
    DerivativeSegment,
    OptionContract,
    OptionType,
    OptionUnderlyingClass,
)
from intraday.domain.market_data.archive import trading_date_for
from intraday.domain.market_data.option_observations import OIObservation, OptionQuote
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.persistence.models import (
    OpenInterestObservation,
    OptionQuoteObservation,
)


class DjangoOptionQuoteRepository:
    """Django ORM implementation of `OptionQuoteRepository`."""

    def save_all(self, quotes: tuple[OptionQuote, ...], *, fetched_at: _dt.datetime) -> None:
        rows = [
            OptionQuoteObservation(
                **_identity_columns(quote.contract, quote.provider, quote.provider_security_id),
                source_timestamp=quote.timestamp,
                fetched_at=fetched_at,
                # Checkpoint 64.78 Phase 13: the SAME canonical IST
                # derivation the equity archive uses (64.73), applied to
                # the PROVIDER's instant, never to `fetched_at` - an
                # option quoted at 15:29:59 IST and written a second
                # later still belongs to the session it printed in.
                trading_date=trading_date_for(quote.timestamp),
                last_price=quote.last_price,
                open_price=quote.open_price,
                high_price=quote.high_price,
                low_price=quote.low_price,
                previous_close=quote.previous_close,
                cumulative_volume=quote.cumulative_volume,
                bid=quote.bid,
                ask=quote.ask,
                bid_quantity=quote.bid_quantity,
                ask_quantity=quote.ask_quantity,
                data_source=quote.data_source,
            )
            for quote in quotes
        ]
        OptionQuoteObservation.objects.bulk_create(rows)

    def get_observations(
        self, *, trading_date: _dt.date, contract_id: str | None = None
    ) -> tuple[OptionQuote, ...]:
        rows = OptionQuoteObservation.objects.filter(trading_date=trading_date)
        if contract_id is not None:
            rows = rows.filter(contract_id=contract_id)
        return tuple(_row_to_option_quote(row) for row in rows.order_by("contract_id", "id"))


class DjangoOIObservationRepository:
    """Django ORM implementation of `OIObservationRepository`."""

    def save_all(
        self, observations: tuple[OIObservation, ...], *, fetched_at: _dt.datetime
    ) -> None:
        rows = [
            OpenInterestObservation(
                **_identity_columns(
                    observation.contract, observation.provider, observation.provider_security_id
                ),
                observed_at=observation.observed_at,
                fetched_at=fetched_at,
                trading_date=trading_date_for(observation.observed_at),
                open_interest=observation.open_interest,
                data_source=observation.data_source,
            )
            for observation in observations
        ]
        OpenInterestObservation.objects.bulk_create(rows)

    def get_observations(
        self, *, trading_date: _dt.date, contract_id: str | None = None
    ) -> tuple[OIObservation, ...]:
        rows = OpenInterestObservation.objects.filter(trading_date=trading_date)
        if contract_id is not None:
            rows = rows.filter(contract_id=contract_id)
        return tuple(_row_to_oi_observation(row) for row in rows.order_by("contract_id", "id"))


def _identity_columns(
    contract: OptionContract, provider: str, security_id: int
) -> dict[str, object]:
    """The identity half of both tables, written from ONE place so the
    two can never drift apart. Stores the canonical `contract_id` AND its
    exploded components: the id is the key, the components make
    "everything for this underlying/expiry" an indexed query instead of
    a string parse."""
    return {
        "contract_id": str(contract.contract_id),
        "exchange": contract.exchange.value,
        "segment": contract.segment.value,
        "underlying_symbol": contract.underlying_symbol,
        "expiry": contract.expiry,
        "strike": contract.strike,
        "option_type": contract.option_type.value,
        "lot_size": contract.lot_size,
        "provider": provider,
        "provider_security_id": security_id,
    }


def _contract_from_row(row: OptionQuoteObservation | OpenInterestObservation) -> OptionContract:
    """Reconstructs the canonical contract from the stored columns.

    `underlying_class` is STOCK unconditionally, and that is a truthful
    reconstruction rather than an assumption: index options cannot reach
    either table. The routing boundary rejects them explicitly
    (`OptionObservationRejectionReason.INDEX_OPTION_NOT_IN_SCOPE`) and
    the subscription builder never asks for them, so an OPTIDX row here
    would mean two independent structural gates had failed. It is
    therefore not stored as a column, because a column implying both
    values are expected would misrepresent the product scope.

    `tick_size` is likewise not persisted - it is exchange-published
    contract SPECIFICATION carried on the identity for convenience, plays
    no part in the natural key, and is not something an observation
    should claim to have witnessed. The instrument master remains its
    source of truth; the canonical tick for NSE option premiums is
    used here so the reconstructed value object is valid."""
    return OptionContract(
        exchange=Exchange(row.exchange),
        segment=DerivativeSegment(row.segment),
        underlying_symbol=row.underlying_symbol,
        underlying_class=OptionUnderlyingClass.STOCK,
        expiry=row.expiry,
        strike=Decimal(row.strike),
        option_type=OptionType(row.option_type),
        lot_size=int(row.lot_size),
        tick_size=Decimal("0.05"),
    )


def _row_to_option_quote(row: OptionQuoteObservation) -> OptionQuote:
    return OptionQuote(
        contract=_contract_from_row(row),
        provider=row.provider,
        provider_security_id=int(row.provider_security_id),
        timestamp=row.source_timestamp,
        last_price=Decimal(row.last_price),
        data_source=row.data_source,
        cumulative_volume=_optional_decimal(row.cumulative_volume),
        open_price=_optional_decimal(row.open_price),
        high_price=_optional_decimal(row.high_price),
        low_price=_optional_decimal(row.low_price),
        previous_close=_optional_decimal(row.previous_close),
        bid=_optional_decimal(row.bid),
        ask=_optional_decimal(row.ask),
        bid_quantity=_optional_decimal(row.bid_quantity),
        ask_quantity=_optional_decimal(row.ask_quantity),
    )


def _row_to_oi_observation(row: OpenInterestObservation) -> OIObservation:
    return OIObservation(
        contract=_contract_from_row(row),
        provider=row.provider,
        provider_security_id=int(row.provider_security_id),
        observed_at=row.observed_at,
        open_interest=int(row.open_interest),
        data_source=row.data_source,
    )


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    """`None` stays `None`, never coerced to `0` - a coerced zero would
    be indistinguishable from "the provider genuinely reported zero",
    the same rule `_row_to_quote()` already applies to cumulative
    volume."""
    return None if value is None else Decimal(value)


__all__ = [
    "DjangoOIObservationRepository",
    "DjangoOptionQuoteRepository",
]
