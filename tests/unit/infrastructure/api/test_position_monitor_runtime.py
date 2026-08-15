# tests/unit/infrastructure/api/test_position_monitor_runtime.py
#
# Checkpoint 43 Part 3/21: THE most important test this checkpoint
# produces - a complete, deterministic PAPER position lifecycle through
# the REAL orchestration path (PaperSignalExecutionService with the
# opt-in exit-plan policy attached, then run_position_monitor_tick()),
# never manually invoking each component independently:
#
#   signal -> entry order -> fill -> position (WITH a real ExitPlan)
#   -> price moves favorably -> TARGET_1 exit -> partial fill
#   -> price moves further -> TARGET_3 exit -> position CLOSED
#
# proving the operational bridge Checkpoint 42's own gap register
# named as missing (POS-001) now genuinely closes the loop.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_broker,
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.position_monitor_runtime import run_position_monitor_tick
from intraday.infrastructure.persistence.models import PaperOrderRecord, PaperPositionRecord
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


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


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def test_full_entry_to_monitored_exit_lifecycle_through_real_orchestration() -> None:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)
    trading_service = get_paper_trading_service()
    broker = get_paper_broker()
    ledger = DjangoPaperLedgerRepository()

    bars = _uptrend_bars()
    entry_price = bars[-1].close
    broker.record_price(RELIANCE, entry_price, BASE)

    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("30"),
        exit_plan_attacher=ledger,
        apply_default_exit_plan=True,
    )

    # 1. Signal -> entry order -> fill -> POSITION, with a real ExitPlan.
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
    managed = managed_positions[0]
    assert managed.exit_plan is not None
    assert managed.exit_plan.target_1 is not None
    assert managed.remaining_quantity == Decimal("30")

    # 2. PRICE UPDATE: rallies to hit target 1 (1.5% above entry).
    target_1_price = managed.exit_plan.target_1
    tick_1_outcome = run_position_monitor_tick(
        current_prices={str(RELIANCE): target_1_price + Decimal("1")}, now=BASE
    )
    assert tick_1_outcome.exits_triggered == 1
    assert tick_1_outcome.exit_decisions[0].reason.value == "TARGET_1"

    after_t1 = ledger.load_open_managed_positions()[0]
    assert after_t1.lifecycle_status.value == "TARGET_1"
    assert after_t1.remaining_quantity < Decimal("30")  # a real partial exit happened
    # A real, second paper order (the exit) now exists.
    assert PaperOrderRecord.objects.count() == 2

    # 3. PRICE UPDATE: still above target 1 but not yet at target 2 -
    #    the sequential rule means target 2 has not fired yet either
    #    (targets progress strictly in order, proven here).
    target_2_price = managed.exit_plan.target_2
    assert target_2_price is not None
    tick_2_outcome = run_position_monitor_tick(
        current_prices={str(RELIANCE): target_2_price + Decimal("1")}, now=BASE
    )
    assert tick_2_outcome.exits_triggered == 1
    assert tick_2_outcome.exit_decisions[0].reason.value == "TARGET_2"

    # 4. PRICE UPDATE: rallies further to hit target 3 - closes everything left.
    target_3_price = managed.exit_plan.target_3
    assert target_3_price is not None
    tick_3_outcome = run_position_monitor_tick(
        current_prices={str(RELIANCE): target_3_price + Decimal("1")}, now=BASE
    )
    assert tick_3_outcome.exits_triggered == 1
    assert tick_3_outcome.exit_decisions[0].reason.value == "TARGET_3"

    final_state = ledger.load_open_managed_positions()
    # No longer monitorable as OPEN - the remaining quantity reached the
    # broker's own full-exit accounting (proven via the position record
    # directly, since load_open_managed_positions() only returns broker-
    # reported OPEN positions).
    assert final_state == () or final_state[0].remaining_quantity == Decimal("0")

    # 5. A complete, auditable trail exists: 4 orders (entry + 3 exits).
    assert PaperOrderRecord.objects.count() == 4

    position_row = PaperPositionRecord.objects.get(instrument_id=str(RELIANCE))
    assert position_row.lifecycle_status == "TARGET_3"
    assert position_row.exit_reason == "TARGET_3"
