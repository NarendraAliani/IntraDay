# tests/unit/infrastructure/persistence/test_signal_repository.py
#
# Checkpoint 62.x: coverage for `DjangoSignalRepository` - the FIRST
# persistence for `domain.signal.contracts.Signal` in this project.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, SignalId
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
BASE = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _record(
    repository: DjangoSignalRepository,
    *,
    signal_id: str,
    strategy_id: str = "ema_crossover",
    instrument_id: InstrumentId = RELIANCE,
    minute_offset: int = 0,
) -> None:
    repository.record_signal(
        signal_id=SignalId(signal_id),
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=BASE + timedelta(minutes=minute_offset),
        risk_status="APPROVED",
        risk_reason="",
        order_status="FILLED",
    )


def test_record_and_list_a_single_signal() -> None:
    repository = DjangoSignalRepository()
    _record(repository, signal_id="sig-1")

    page = repository.list_signals()

    assert page.total_count == 1
    assert len(page.items) == 1
    assert page.items[0].record.signal_id == "sig-1"


def test_recording_the_same_signal_id_twice_never_duplicates() -> None:
    """`signal_id` is deterministic - a duplicate `record_signal()` call
    for the identical signal must update the existing row, never create
    a second one."""
    repository = DjangoSignalRepository()
    _record(repository, signal_id="sig-1")
    _record(repository, signal_id="sig-1")

    page = repository.list_signals()

    assert page.total_count == 1


def test_pagination_returns_the_correct_page() -> None:
    repository = DjangoSignalRepository()
    for i in range(5):
        _record(repository, signal_id=f"sig-{i}", minute_offset=i)

    first_page = repository.list_signals(page=1, page_size=2)
    second_page = repository.list_signals(page=2, page_size=2)

    assert first_page.total_count == 5
    assert len(first_page.items) == 2
    assert len(second_page.items) == 2
    assert {item.record.signal_id for item in first_page.items}.isdisjoint(
        {item.record.signal_id for item in second_page.items}
    )


def test_filter_by_strategy_id() -> None:
    repository = DjangoSignalRepository()
    _record(repository, signal_id="sig-a", strategy_id="ema_crossover")
    _record(repository, signal_id="sig-b", strategy_id="sma_trend_filter")

    page = repository.list_signals(strategy_id="sma_trend_filter")

    assert page.total_count == 1
    assert page.items[0].record.signal_id == "sig-b"


def test_filter_by_instrument_id() -> None:
    repository = DjangoSignalRepository()
    _record(repository, signal_id="sig-a", instrument_id=RELIANCE)
    _record(repository, signal_id="sig-b", instrument_id=TCS)

    page = repository.list_signals(instrument_id=str(TCS))

    assert page.total_count == 1
    assert page.items[0].record.signal_id == "sig-b"


def test_page_size_is_bounded_to_200() -> None:
    repository = DjangoSignalRepository()
    _record(repository, signal_id="sig-1")

    page = repository.list_signals(page_size=10000)

    assert page.page_size == 200
