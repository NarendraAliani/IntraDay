# tests/unit/infrastructure/api/test_end_to_end_paper_session.py
#
# Checkpoint 51 Part 21: THE acceptance test for this checkpoint - the
# first proof that this project's already-existing, already-tested
# real components chain together into one complete PAPER session:
#
#   BARS (deterministic replay - see module docstring below for why)
#   -> run_active_loop_tick() [signal -> risk -> paper order -> fill]
#   -> position (with a real ExitPlan)
#   -> run_position_monitor_tick() [price update, no exit fires yet]
#   -> run_eod_sequence() [square-off -> reconcile -> zero exposure ->
#      realized P&L]
#
# without manually mutating any internal state - every step calls the
# same real, scheduler-shaped function a Celery task would call.
#
# HONEST, NAMED LIMITATION (this checkpoint's own explicit "never fake
# live capability" instruction): `bars` here are DETERMINISTIC REPLAY
# data, constructed the exact same way this project's own established
# lifecycle test (`test_full_entry_to_monitored_exit_lifecycle_through_
# real_orchestration`, Checkpoint 43) already does - NOT a real Dhan
# WebSocket feed, which does not exist in this codebase yet (see
# ACTIVE_PRODUCT_GAP_REGISTER.md). This test proves the DOWNSTREAM
# chain (signal -> risk -> order -> fill -> position -> monitor -> EOD
# -> reconciliation -> P&L) is real and wired; it does NOT prove live
# market-data ingestion, which remains a separate, undone dependency.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api.eod_runtime import run_eod_sequence
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_broker,
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.position_monitor_runtime import run_position_monitor_tick
from intraday.infrastructure.persistence.eod_run_repository import EODRunStatus
from intraday.infrastructure.persistence.models import EODRun, PaperOrderRecord
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _bars(prices: list[int]) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(price - 1),
            high=Decimal(price + 1),
            low=Decimal(price - 2),
            close=Decimal(price),
            volume=Decimal("0"),
        )
        for i, price in enumerate(prices)
    )


def _uptrend_bars() -> tuple[Bar, ...]:
    flat = [100] * 8
    up = [101 + i for i in range(10)]
    return _bars(flat + up)


def _config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


def test_one_complete_paper_session_from_signal_through_eod() -> None:
    """DATA -> BAR -> SIGNAL -> RISK -> PAPER ORDER -> FILL -> POSITION
    -> MONITOR -> EOD SQUARE-OFF -> RECONCILIATION -> ZERO EXPOSURE ->
    REALIZED P&L, entirely through real orchestration functions."""
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)
    trading_service = get_paper_trading_service()
    ledger = DjangoPaperLedgerRepository()

    bars = _uptrend_bars()
    entry_price = bars[-1].close
    trading_service.broker.record_price(RELIANCE, entry_price, BASE)

    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        exit_plan_attacher=ledger,
        apply_default_exit_plan=True,
    )

    # 1. DATA -> BAR -> SIGNAL -> RISK -> PAPER ORDER -> FILL -> POSITION.
    result = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.order_result is not None
    assert result.order_result.broker_report is not None
    assert result.order_result.broker_report.status.value == "FILLED"

    managed_positions = ledger.load_open_managed_positions()
    assert len(managed_positions) == 1
    assert managed_positions[0].exit_plan is not None

    # 2. MONITOR: a price update that does NOT hit any exit target -
    #    the position stays open into EOD, exactly the scenario that
    #    exercises EOD's own force-close, not the ordinary exit path
    #    Checkpoint 43's test already proves.
    monitor_outcome = run_position_monitor_tick(
        current_prices={str(RELIANCE): entry_price + Decimal("1")}, now=BASE
    )
    assert monitor_outcome.exits_triggered == 0
    assert ledger.load_open_managed_positions()[0].lifecycle_status.value == "OPEN"

    # 3. EOD: SQUARE_OFF -> RECONCILE -> ZERO EXPOSURE -> P&L -> CLOSE.
    eod_time = BASE + timedelta(hours=6)  # well past market close
    eod_outcome = run_eod_sequence(
        current_prices={str(RELIANCE): entry_price + Decimal("2")}, now=eod_time
    )

    assert eod_outcome.already_handled is False
    assert eod_outcome.square_off is not None
    assert eod_outcome.square_off.positions_found == 1
    assert eod_outcome.square_off.positions_closed == 1
    assert eod_outcome.square_off.positions_failed == ()
    assert eod_outcome.reconciliation_divergence_count == 0
    assert eod_outcome.zero_exposure_confirmed is True
    assert eod_outcome.total_realized_pnl is not None
    assert eod_outcome.total_realized_pnl > Decimal("0")  # exited above entry

    # 4. FINAL STATE: broker reports the position CLOSED, exactly one
    #    entry order and one EOD exit order, EOD run durably COMPLETED.
    assert get_paper_broker().get_positions()[0].status.value == "CLOSED"
    assert PaperOrderRecord.objects.count() == 2
    eod_row = EODRun.objects.get(eod_date=eod_time.date())
    assert eod_row.status == EODRunStatus.COMPLETED.value

    # 5. Re-running EOD for the SAME date must be a genuine no-op - the
    #    session is durably closed, never re-processed.
    repeat = run_eod_sequence(
        current_prices={str(RELIANCE): entry_price + Decimal("2")}, now=eod_time
    )
    assert repeat.already_handled is True
    assert PaperOrderRecord.objects.count() == 2  # still exactly 2 - no duplicate exit
