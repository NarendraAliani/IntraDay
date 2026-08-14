# tests/unit/research/test_bar_semantics_and_bias_audit.py
#
# Checkpoint 28 Part 12/13: bar-semantics and quantitative-bias audit
# tests. Backtesting reuses `HistoricalMarketDataService.get_bars()`
# (Checkpoint 14/18/27) exactly, which already calls
# `domain.market_data.quality.ensure_chronological()` - these tests
# prove that reuse mechanically (not by re-implementing chronological
# validation inside `research.backtesting`, which would duplicate
# Checkpoint 14's own logic).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


class _FakeRepository:
    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._bars = bars

    def get_bars(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        return self._bars


def _bar(minute: int, price: str) -> Bar:
    p = Decimal(price)
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=minute),
        open=p,
        high=p + 1,
        low=p - 1,
        close=p,
        volume=Decimal("0"),
    )


def test_duplicate_bar_timestamps_are_rejected_before_reaching_the_backtest_engine() -> None:
    corrupt_bars = (_bar(0, "100"), _bar(0, "101"))  # same timestamp twice
    service = HistoricalMarketDataService(repository=_FakeRepository(corrupt_bars))
    with pytest.raises(DuplicateBarTimestampError):
        service.get_bars(RELIANCE, Timeframe.ONE_MINUTE, BASE, BASE + timedelta(minutes=5))


def test_out_of_order_bars_are_rejected_before_reaching_the_backtest_engine() -> None:
    corrupt_bars = (_bar(1, "101"), _bar(0, "100"))  # bar[1] before bar[0] chronologically
    service = HistoricalMarketDataService(repository=_FakeRepository(corrupt_bars))
    with pytest.raises(OutOfOrderBarError):
        service.get_bars(RELIANCE, Timeframe.ONE_MINUTE, BASE, BASE + timedelta(minutes=5))


def test_clean_chronological_bars_pass_through_unchanged() -> None:
    clean_bars = tuple(_bar(i, str(100 + i)) for i in range(5))
    service = HistoricalMarketDataService(repository=_FakeRepository(clean_bars))
    result = service.get_bars(RELIANCE, Timeframe.ONE_MINUTE, BASE, BASE + timedelta(minutes=5))
    assert result == clean_bars
