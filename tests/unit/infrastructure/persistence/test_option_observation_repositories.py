# tests/unit/infrastructure/persistence/test_option_observation_repositories.py
#
# Checkpoint 64.78: real-database coverage for option-observation
# persistence - contract/provider identity, canonical trading-date
# stamping at the write boundary, append-only idempotency semantics, and
# round-tripping back into the canonical domain contracts.
#
# No provider connection, no WebSocket, no order path. Every contract
# comes from the SYNTHETIC 64.77 fixture.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.options import OptionInstrumentRecord
from intraday.domain.market_data.option_observations import OIObservation, OptionQuote
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    parse_option_scrip_master,
)
from intraday.infrastructure.persistence.models import (
    OpenInterestObservation,
    OptionQuoteObservation,
)
from intraday.infrastructure.persistence.option_market_data_repositories import (
    DjangoOIObservationRepository,
    DjangoOptionQuoteRepository,
)
from tests.unit.research.checkpoint_64_77_option_fixtures import SCRIP_MASTER_CSV

pytestmark = pytest.mark.django_db

# 03:50 UTC = 09:20 IST - inside the window where a naive `.date()` on
# the UTC instant would still give the right day, and 20:00 UTC the day
# before, where it would not.
MORNING = datetime(2026, 9, 15, 3, 50, tzinfo=UTC)
PREVIOUS_EVENING = datetime(2026, 9, 14, 20, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 9, 15, 3, 50, 1, tzinfo=UTC)


def _record() -> OptionInstrumentRecord:
    records = parse_option_scrip_master(SCRIP_MASTER_CSV)
    for record in records:
        if record.provider_identity.security_id == 9000001:
            return record
    raise AssertionError("fixture changed")


def _quote(*, timestamp: datetime = MORNING, last_price: str = "42.5") -> OptionQuote:
    record = _record()
    return OptionQuote(
        contract=record.contract,
        provider=record.provider_identity.provider,
        provider_security_id=record.provider_identity.security_id,
        timestamp=timestamp,
        last_price=Decimal(last_price),
        data_source="dhan_websocket",
        cumulative_volume=Decimal("12500"),
        open_price=Decimal("40"),
        high_price=Decimal("45"),
        low_price=Decimal("38"),
        previous_close=Decimal("39"),
    )


def _oi(*, observed_at: datetime = MORNING, open_interest: int = 87_500) -> OIObservation:
    record = _record()
    return OIObservation(
        contract=record.contract,
        provider=record.provider_identity.provider,
        provider_security_id=record.provider_identity.security_id,
        observed_at=observed_at,
        open_interest=open_interest,
        data_source="dhan_websocket",
    )


def test_option_quote_is_persisted_with_full_historical_identity() -> None:
    DjangoOptionQuoteRepository().save_all((_quote(),), fetched_at=FETCHED_AT)

    row = OptionQuoteObservation.objects.get()
    assert row.contract_id == "NSE:FNO:RELIANCE:2026-09-24:2400:CE"
    assert row.underlying_symbol == "RELIANCE"
    assert row.expiry.isoformat() == "2026-09-24"
    assert row.strike == Decimal("2400.0000")
    assert row.option_type == "CE"
    assert row.segment == "NSE_FNO"
    assert row.lot_size == 500
    assert row.provider == "DHAN"
    assert row.provider_security_id == 9000001
    assert row.data_source == "dhan_websocket"
    assert row.trading_date.isoformat() == "2026-09-15"
    assert row.fetched_at == FETCHED_AT
    assert row.source_timestamp == MORNING


def test_oi_observation_is_persisted_independently_of_any_quote() -> None:
    DjangoOIObservationRepository().save_all((_oi(),), fetched_at=FETCHED_AT)

    assert OptionQuoteObservation.objects.count() == 0
    row = OpenInterestObservation.objects.get()
    assert row.open_interest == 87_500
    assert row.contract_id == "NSE:FNO:RELIANCE:2026-09-24:2400:CE"
    assert row.trading_date.isoformat() == "2026-09-15"


def test_trading_date_uses_the_canonical_ist_derivation_not_utc_date() -> None:
    """An observation at 20:00 UTC on the 14th is 01:30 IST on the 15th;
    the canonical derivation is the ONE place that is decided."""
    DjangoOIObservationRepository().save_all(
        (_oi(observed_at=PREVIOUS_EVENING),), fetched_at=FETCHED_AT
    )

    row = OpenInterestObservation.objects.get()
    assert row.observed_at.date().isoformat() == "2026-09-14"
    assert row.trading_date.isoformat() == "2026-09-15"


def test_two_prints_sharing_one_timestamp_are_both_preserved() -> None:
    """Checkpoint 64.78 Phase 12 / the 64.73 Phase 11 lesson: Dhan's
    last-trade-time has one-SECOND resolution and a liquid strike trades
    many times within a second. An append-only table with no unique
    constraint keeps both real events; a (contract, timestamp) unique
    constraint would silently destroy one of them."""
    repository = DjangoOptionQuoteRepository()

    repository.save_all(
        (_quote(last_price="42.5"), _quote(last_price="42.6")), fetched_at=FETCHED_AT
    )

    rows = OptionQuoteObservation.objects.order_by("id")
    assert rows.count() == 2
    assert [r.last_price for r in rows] == [Decimal("42.5000"), Decimal("42.6000")]
    assert len({r.source_timestamp for r in rows}) == 1


def test_repeated_oi_readings_at_one_instant_are_both_preserved() -> None:
    DjangoOIObservationRepository().save_all(
        (_oi(open_interest=87_500), _oi(open_interest=87_600)), fetched_at=FETCHED_AT
    )

    assert OpenInterestObservation.objects.count() == 2


def test_option_observations_never_touch_the_equity_quote_table() -> None:
    """The equity path must remain completely unchanged - option
    observations are NOT routed into `LiveQuoteObservation`."""
    from intraday.infrastructure.persistence.models import LiveQuoteObservation

    DjangoOptionQuoteRepository().save_all((_quote(),), fetched_at=FETCHED_AT)
    DjangoOIObservationRepository().save_all((_oi(),), fetched_at=FETCHED_AT)

    assert LiveQuoteObservation.objects.count() == 0


def test_option_quote_round_trips_back_into_the_canonical_contract() -> None:
    repository = DjangoOptionQuoteRepository()
    repository.save_all((_quote(),), fetched_at=FETCHED_AT)

    (restored,) = repository.get_observations(trading_date=MORNING.date())

    assert restored.contract_id == _quote().contract_id
    assert restored.last_price == Decimal("42.5")
    assert restored.cumulative_volume == Decimal("12500")
    assert restored.previous_close == Decimal("39")
    assert restored.bid is None  # never coerced to zero
    assert restored.provider_security_id == 9000001
    assert restored.data_source == "dhan_websocket"


def test_oi_observation_round_trips_and_filters_by_contract() -> None:
    repository = DjangoOIObservationRepository()
    repository.save_all((_oi(),), fetched_at=FETCHED_AT)

    (restored,) = repository.get_observations(
        trading_date=MORNING.date(), contract_id="NSE:FNO:RELIANCE:2026-09-24:2400:CE"
    )
    assert restored.open_interest == 87_500
    assert (
        repository.get_observations(
            trading_date=MORNING.date(), contract_id="NSE:FNO:RELIANCE:2026-09-24:2500:PE"
        )
        == ()
    )


def test_a_whole_trading_day_is_queryable_for_a_future_option_archive() -> None:
    """Phase 14: this checkpoint does NOT implement an option daily
    archive; it only proves the identity needed by a future one -
    trading_date + contract identity + provider + data_source - is
    present and queryable."""
    DjangoOptionQuoteRepository().save_all((_quote(),), fetched_at=FETCHED_AT)

    rows = OptionQuoteObservation.objects.filter(trading_date=MORNING.date())
    assert rows.count() == 1
    assert set(rows.values_list("data_source", flat=True)) == {"dhan_websocket"}
