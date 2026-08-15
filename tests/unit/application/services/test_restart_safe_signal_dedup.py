# tests/unit/application/services/test_restart_safe_signal_dedup.py
#
# Checkpoint 39 Part F: proves "restart does not duplicate processing"
# with REAL persisted evidence - a fresh, unrelated
# PaperSignalExecutionService instance (simulating a process restart:
# no shared in-memory state with the first call) still refuses to
# re-submit an order for a signal that was already processed, by
# reloading `already_processed_signal_ids` from the durable ledger.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("50000"),
    max_position_size=Decimal("1000"),
    max_per_trade_risk=Decimal("10000"),
)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


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


def _fresh_service_sharing_the_broker(broker: PaperBroker) -> PaperSignalExecutionService:
    """Simulates a process restart in the one way this test CAN
    honestly simulate it: a brand-new coordinator/service instance,
    with NO shared in-memory dedup state - only the durable ledger
    (queried fresh via `load_processed_signal_ids()`) can prevent a
    duplicate. `PaperBroker`'s own in-memory state is intentionally
    still shared here because Checkpoint 34 already established
    (and Checkpoint 36's `PAPER_TRADING_ARCHITECTURE.md` documents)
    that a TRUE process restart resets `PaperBroker` to empty - a
    full broker-state-reconstruction-from-ledger capability does not
    exist yet (a separate, already-tracked gap, see
    `RUNTIME_ARCHITECTURE_DECISION.md`). This test isolates and proves
    ONLY the signal-dedup half of restart safety."""
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)
    ledger = DjangoPaperLedgerRepository()
    trading_service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: BASE,
        ledger=ledger,
    )
    return PaperSignalExecutionService(
        coordinator=coordinator, paper_trading_service=trading_service, quantity=Decimal("10")
    )


def test_restart_safe_dedup_uses_the_persisted_ledger_not_in_memory_state() -> None:
    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    broker.record_price(RELIANCE, _uptrend_bars()[-1].close, BASE)
    ledger = DjangoPaperLedgerRepository()

    # "Before restart": evaluate and submit once.
    first_service = _fresh_service_sharing_the_broker(broker)
    first_result = first_service.evaluate_and_submit(
        bars=_uptrend_bars(),
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=ledger.load_processed_signal_ids(),  # empty before restart
        already_submitted_idempotency_keys=frozenset(),
    )
    assert first_result.order_result is not None
    assert first_result.order_result.broker_report is not None
    assert first_result.order_result.broker_report.status.value == "FILLED"
    assert len(broker.get_orders()) == 1

    # "After restart": a completely fresh service/coordinator instance,
    # re-evaluating the SAME bar series - the persisted ledger (not any
    # in-memory set) is what must prevent a second order.
    second_service = _fresh_service_sharing_the_broker(broker)
    second_result = second_service.evaluate_and_submit(
        bars=_uptrend_bars(),
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=ledger.load_processed_signal_ids(),  # reloaded from disk
        already_submitted_idempotency_keys=frozenset(),
    )

    assert second_result.skipped_reason == "signal_already_processed"
    assert len(broker.get_orders()) == 1  # still only one order after the "restart"
