# tests/unit/application/services/test_paper_signal_execution_trade_plan.py
#
# Checkpoint 64.7: end-to-end proof that a strategy-produced TradePlan
# (`atr_volatility_breakout`, the ONE producing strategy - Checkpoint
# 64.7 §4) is persisted through the REAL `PaperSignalExecutionService`
# bridge and its real stop_loss/target values flow into the outbound
# communication message - never fabricated, and never present for a
# strategy (e.g. ema_crossover) that does not produce a plan.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.signal_communication import (
    NotificationRouter,
    SignalCommunicationService,
)
from intraday.application.services.strategy_execution import build_coordinator as _build_coordinator
from intraday.communication.contracts.signal_communication import CommunicationChannel
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.trade_plan_repository import DjangoTradePlanRepository
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("50000"),
    max_position_size=Decimal("1000"),
    max_per_trade_risk=Decimal("10000"),
)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _breakout_bars() -> tuple[Bar, ...]:
    flat = [
        Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(100),
            high=Decimal(101),
            low=Decimal(99),
            close=Decimal(100),
            volume=Decimal("0"),
        )
        for i in range(8)
    ]
    breakout = Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=9),
        open=Decimal(100),
        high=Decimal(112),
        low=Decimal(99),
        close=Decimal(111),
        volume=Decimal("0"),
    )
    return (*flat, breakout)


def _atr_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "atr_volatility_breakout",
        "v1",
        "v1",
        "v1",
        {
            "lookback": 5,
            "atr_multiplier": Decimal("0.1"),
            "stop_loss_atr_multiplier": Decimal("1.0"),
            "target_1_atr_multiplier": Decimal("1.5"),
            "target_2_atr_multiplier": Decimal("2.5"),
            "target_3_atr_multiplier": Decimal("4.0"),
            "trailing_stop_atr_multiplier": Decimal("1.0"),
        },
    )


@dataclass
class FakeProvider:
    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****abcd"
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        return True, "msg-1", None, None, False


def _bridge() -> tuple[PaperSignalExecutionService, PaperBroker, FakeProvider]:
    registry = build_default_registry()
    registry.activate("atr_volatility_breakout")
    coordinator = _build_coordinator(registry)
    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    trading_service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: BASE,
    )
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    communication = SignalCommunicationService(
        router=NotificationRouter(providers=(telegram,), ledger=None)
    )
    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
        trade_plan_recorder=DjangoTradePlanRepository(),
    )
    return service, broker, telegram


@pytest.mark.django_db
def test_a_real_trade_plan_is_persisted_and_its_values_reach_the_outbound_message() -> None:
    service, broker, telegram = _bridge()
    bars = _breakout_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

    result = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="atr_volatility_breakout",
        configuration=_atr_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert result.signal_id is not None
    from intraday.infrastructure.persistence.models import TradePlanRecord

    record = TradePlanRecord.objects.get(signal_id=str(result.signal_id))
    assert record.stop_loss is not None
    assert record.target_1 is not None
    assert record.target_2 is not None
    assert record.target_3 is not None
    assert record.target_1 < record.target_2 < record.target_3

    # The outbound VALIDATED_SIGNAL message must carry the SAME real
    # values just persisted - never "-"/None for this strategy.
    validated_message = telegram.sent[0]
    assert "VALIDATED SIGNAL" in validated_message
    assert (
        str(record.stop_loss) in validated_message or f"{record.stop_loss:.2f}" in validated_message
    )
    assert "Target 1" in validated_message


@pytest.mark.django_db
def test_ema_crossover_signal_still_carries_no_trade_plan_in_its_message() -> None:
    """Regression guard: wiring the TradePlan-producing strategy through
    the bridge must NOT change behavior for a strategy that produces no
    plan - stop_loss/targets remain honestly absent."""
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = _build_coordinator(registry)
    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    trading_service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: BASE,
    )
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    communication = SignalCommunicationService(
        router=NotificationRouter(providers=(telegram,), ledger=None)
    )
    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
        trade_plan_recorder=DjangoTradePlanRepository(),
    )
    bars = tuple(
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
        for i, price in enumerate([100] * 8 + [101 + i for i in range(10)])
    )
    broker.record_price(RELIANCE, bars[-1].close, BASE)

    result = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=StrategyConfigurationValues(
            "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert result.signal_id is not None
    from intraday.infrastructure.persistence.models import TradePlanRecord

    assert not TradePlanRecord.objects.filter(signal_id=str(result.signal_id)).exists()
    assert "Stop Loss: -" in telegram.sent[0]
