# tests/unit/infrastructure/api/test_active_loop_runtime.py
#
# Checkpoint 40 Part 3-7: proves `run_active_loop_tick()` - the one
# function a scheduler would call repeatedly - is genuinely session-
# aware and restart-safe, composed from REAL infrastructure
# (PaperBroker/DjangoPaperLedgerRepository via the existing composition
# root), not a synthetic stand-in.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.session.contracts import SessionStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api.active_loop_runtime import (
    run_active_loop_tick,
    run_active_loop_tick_from_source,
)
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.market_data_providers.replay.deterministic_bar_source import (
    DeterministicReplayBarSource,
)
from intraday.infrastructure.persistence.models import PaperOrderRecord
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")

# 2026-01-05 is a Monday, not an NSE_HOLIDAYS_2026 date.
MARKET_OPEN_INSTANT = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # ~11:30 IST, well inside OPEN
MARKET_HOLIDAY_INSTANT = datetime(2026, 1, 26, 6, 0, tzinfo=UTC)  # Republic Day 2026
# Checkpoint 64.6 §10: the square-off/entry-cutoff window itself -
# SQUARE_OFF_DEADLINE_IST is 15:20 IST (09:50 UTC), MARKET_CLOSE_IST is
# 15:30 IST (10:00 UTC) - 09:55 UTC falls strictly inside
# [square_off_deadline, market_close), i.e. SessionStatus.CLOSING, not
# CLOSED or HOLIDAY. Distinct from the already-tested HOLIDAY case -
# proves the entry-cutoff rule itself is enforced, not just "some
# session-status check exists."
MARKET_CLOSING_WINDOW_INSTANT = datetime(2026, 1, 5, 9, 55, tzinfo=UTC)


def _bars(prices: list[int], base: datetime) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=base + timedelta(minutes=i + 1),
            open=Decimal(price - 1),
            high=Decimal(price + 1),
            low=Decimal(price - 2),
            close=Decimal(price),
            volume=Decimal("0"),
        )
        for i, price in enumerate(prices)
    )


def _uptrend_bars(base: datetime) -> tuple[Bar, ...]:
    flat = [100] * 8
    up = [101 + i for i in range(10)]
    return _bars(flat + up, base)


def _config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def test_tick_is_skipped_on_a_holiday_without_evaluating_the_strategy() -> None:
    outcome = run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=_uptrend_bars(MARKET_HOLIDAY_INSTANT),
        now=MARKET_HOLIDAY_INSTANT,
    )
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.HOLIDAY
    assert "market_session_not_open" in (outcome.skipped_reason or "")
    assert not PaperOrderRecord.objects.exists()


def test_tick_is_skipped_during_the_square_off_window_no_new_entry_after_cutoff() -> None:
    """Checkpoint 64.6 §10: audits and proves the entry-cutoff rule
    (`SQUARE_OFF_DEADLINE_IST`, `domain/session/calendar.py`) is
    genuinely ENFORCED at the point a new order would be created, not
    merely defined as a constant. `SessionStatus.CLOSING` (the market
    is still technically open until `market_close`, but past
    `square_off_deadline`) must be rejected exactly like `HOLIDAY` -
    both mean "no new order may be submitted" per the session
    contract's own documented rule."""
    outcome = run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=_uptrend_bars(MARKET_CLOSING_WINDOW_INSTANT),
        now=MARKET_CLOSING_WINDOW_INSTANT,
    )
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.CLOSING
    assert "market_session_not_open" in (outcome.skipped_reason or "")
    assert not PaperOrderRecord.objects.exists()


def test_tick_with_no_bars_is_skipped_cleanly() -> None:
    outcome = run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=(),
        now=MARKET_OPEN_INSTANT,
    )
    assert outcome.ran is False
    assert outcome.skipped_reason == "no_bars_supplied"


def test_tick_during_open_session_runs_and_produces_a_persisted_order() -> None:
    trading_service = get_paper_trading_service()
    bars = _uptrend_bars(MARKET_OPEN_INSTANT)
    trading_service.broker.record_price(RELIANCE, bars[-1].close, MARKET_OPEN_INSTANT)

    outcome = run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=bars,
        now=MARKET_OPEN_INSTANT,
    )

    assert outcome.ran is True
    assert outcome.session_status is SessionStatus.OPEN
    assert PaperOrderRecord.objects.exclude(signal_id="").exists()


def test_second_tick_with_the_same_bars_does_not_duplicate_the_order() -> None:
    """Restart-safety, exercised through the REAL scheduler-shaped
    entrypoint - not just the lower-level service directly
    (Checkpoint 39 proved the lower-level primitive; this proves the
    composition root wires it correctly)."""
    trading_service = get_paper_trading_service()
    bars = _uptrend_bars(MARKET_OPEN_INSTANT)
    trading_service.broker.record_price(RELIANCE, bars[-1].close, MARKET_OPEN_INSTANT)

    run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=bars,
        now=MARKET_OPEN_INSTANT,
    )
    first_order_count = PaperOrderRecord.objects.count()

    run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=bars,
        now=MARKET_OPEN_INSTANT,
    )
    second_order_count = PaperOrderRecord.objects.count()

    assert second_order_count == first_order_count


def test_active_loop_from_source_is_driven_purely_through_the_bar_source_boundary() -> None:
    """Checkpoint 52: the caller no longer manually slices/assembles
    `bars` on each call - it supplies a `BarSource` ONCE, and
    `run_active_loop_tick_from_source()` pulls whatever is available
    `as_of` the current clock, exactly the calling pattern a real
    scheduled task (against a real future Dhan-backed `BarSource`)
    would use. Called TWICE with an advancing clock, simulating two
    scheduler ticks - proves no duplicate order results, using the
    SAME underlying idempotency `run_active_loop_tick()` already had,
    now reached through the new source-driven entrypoint."""
    trading_service = get_paper_trading_service()
    bars = _uptrend_bars(MARKET_OPEN_INSTANT)
    trading_service.broker.record_price(RELIANCE, bars[-1].close, MARKET_OPEN_INSTANT)
    source = DeterministicReplayBarSource.seeded(bars)

    all_bars_available_at = MARKET_OPEN_INSTANT + timedelta(minutes=len(bars) + 1)

    first_tick = run_active_loop_tick_from_source(
        source=source,
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        strategy_id="ema_crossover",
        configuration=_config(),
        now=all_bars_available_at,
    )
    assert first_tick.ran is True
    assert PaperOrderRecord.objects.exclude(signal_id="").exists()
    first_order_count = PaperOrderRecord.objects.count()

    # Second scheduler tick, clock advanced - the SAME bars are still
    # all that's "available" (the replay source never adds more), so
    # this must be a genuine no-op, not a duplicate order.
    second_tick = run_active_loop_tick_from_source(
        source=source,
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        strategy_id="ema_crossover",
        configuration=_config(),
        now=all_bars_available_at + timedelta(minutes=1),
    )
    assert second_tick.ran is True  # bars were still available, market still open
    assert PaperOrderRecord.objects.count() == first_order_count


def test_active_loop_from_source_reveals_no_bars_before_they_exist() -> None:
    """Before ANY bar's timestamp has arrived, the source-driven tick
    must behave exactly like a real live feed with nothing to say yet -
    `skipped_reason="no_bars_supplied"`, never a fabricated signal."""
    source = DeterministicReplayBarSource.seeded(_uptrend_bars(MARKET_OPEN_INSTANT))

    outcome = run_active_loop_tick_from_source(
        source=source,
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        strategy_id="ema_crossover",
        configuration=_config(),
        now=MARKET_OPEN_INSTANT,  # before the first seeded bar's timestamp
    )

    assert outcome.ran is False
    assert outcome.skipped_reason == "no_bars_supplied"
