# tests/unit/infrastructure/market_data_providers/test_deterministic_bar_source.py
#
# Checkpoint 52: coverage for `DeterministicReplayBarSource` in
# isolation - no Django, no I/O, purely proving the `BarSource`
# contract (only bars with `timestamp <= as_of` are ever revealed,
# grouped correctly per instrument/timeframe).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.replay.deterministic_bar_source import (
    DeterministicReplayBarSource,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
BASE = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _bar(instrument_id, minute: int, price: int) -> Bar:  # type: ignore[no-untyped-def]
    return Bar(
        instrument_id=instrument_id,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=minute),
        open=Decimal(price - 1),
        high=Decimal(price + 1),
        low=Decimal(price - 2),
        close=Decimal(price),
        volume=Decimal("0"),
    )


def test_reveals_no_bars_before_the_first_timestamp() -> None:
    source = DeterministicReplayBarSource.seeded((_bar(RELIANCE, 1, 100), _bar(RELIANCE, 2, 101)))

    revealed = source.get_bars(instrument_id=RELIANCE, timeframe=Timeframe.ONE_MINUTE, as_of=BASE)

    assert revealed == ()


def test_reveals_only_bars_at_or_before_as_of() -> None:
    bars = (_bar(RELIANCE, 1, 100), _bar(RELIANCE, 2, 101), _bar(RELIANCE, 3, 102))
    source = DeterministicReplayBarSource.seeded(bars)

    revealed = source.get_bars(
        instrument_id=RELIANCE, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=2)
    )

    assert revealed == (bars[0], bars[1])


def test_later_calls_with_an_advancing_as_of_reveal_more_bars() -> None:
    """The exact calling pattern a real scheduled task would use -
    calling repeatedly with `now` advancing over time."""
    bars = tuple(_bar(RELIANCE, i, 100 + i) for i in range(1, 6))
    source = DeterministicReplayBarSource.seeded(bars)

    first = source.get_bars(
        instrument_id=RELIANCE, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=2)
    )
    second = source.get_bars(
        instrument_id=RELIANCE, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=5)
    )

    assert len(first) == 2
    assert len(second) == 5
    assert first == second[:2]  # strictly a superset, never revises already-revealed bars


def test_different_instruments_are_kept_separate() -> None:
    source = DeterministicReplayBarSource.seeded((_bar(RELIANCE, 1, 100), _bar(TCS, 1, 3000)))

    reliance_bars = source.get_bars(
        instrument_id=RELIANCE, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=5)
    )
    tcs_bars = source.get_bars(
        instrument_id=TCS, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=5)
    )

    assert len(reliance_bars) == 1
    assert len(tcs_bars) == 1
    assert reliance_bars[0].close == Decimal("100")
    assert tcs_bars[0].close == Decimal("3000")


def test_unknown_instrument_reveals_nothing_never_raises() -> None:
    source = DeterministicReplayBarSource.seeded((_bar(RELIANCE, 1, 100),))

    revealed = source.get_bars(
        instrument_id=TCS, timeframe=Timeframe.ONE_MINUTE, as_of=BASE + timedelta(minutes=5)
    )

    assert revealed == ()
