# tests/unit/application/services/test_paper_signal_execution_communication.py
#
# Checkpoint 37 Part 3/6: proves SIGNAL TRUTH != EXECUTION TRUTH inside
# the REAL Strategy -> Signal -> Risk -> Paper Order bridge
# (`PaperSignalExecutionService`, Checkpoint 36) - a signal is
# communicated whether the resulting order is filled, blocked by the
# kill switch, or never evaluated at all.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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


@dataclass
class FakeProvider:
    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****abcd"
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        return True, "msg-1", None, None, False


def _bridge(
    *, kill_switch: TradingHaltStatus
) -> tuple[PaperSignalExecutionService, PaperBroker, FakeProvider]:
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
        kill_switch_status_provider=lambda: kill_switch,
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
    )
    return service, broker, telegram


def test_scenario_g_filled_signal_communicates_validated_then_filled() -> None:
    service, broker, telegram = _bridge(kill_switch=TradingHaltStatus.ACTIVE)
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

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
    # Two messages: the validated signal itself, then the fill outcome.
    assert len(telegram.sent) == 2
    assert "VALIDATED SIGNAL" in telegram.sent[0]
    assert "ORDER FILLED" in telegram.sent[1]


def test_scenario_d_kill_switch_still_communicates_the_signal_and_the_block_reason() -> None:
    """The defining proof of SIGNAL TRUTH != EXECUTION TRUTH: the kill
    switch stops the ORDER, never the COMMUNICATION."""
    service, broker, telegram = _bridge(kill_switch=TradingHaltStatus.HALTED)
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

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
    assert result.order_result.risk_decision.outcome.value == "REJECTED"
    assert broker.get_orders() == ()  # no order reached the broker

    # But the signal WAS communicated, twice: the validated signal, and
    # the execution-blocked follow-up with the real reason.
    assert len(telegram.sent) == 2
    assert "VALIDATED SIGNAL" in telegram.sent[0]
    assert "EXECUTION BLOCKED" in telegram.sent[1]


def test_flat_bars_produce_no_signal_and_no_communication() -> None:
    """A NEUTRAL direction never becomes a signal at all - nothing to
    communicate, proven by zero sends, not an empty/blank message."""
    service, broker, telegram = _bridge(kill_switch=TradingHaltStatus.ACTIVE)
    bars = _bars([100] * 10)
    broker.record_price(RELIANCE, Decimal("100"), BASE)

    service.evaluate_and_submit(
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

    assert telegram.sent == []


def test_no_communication_service_configured_does_not_break_the_bridge() -> None:
    """Communication is OPTIONAL - a caller that never wires it must
    see identical order-submission behavior to Checkpoint 36's
    original bridge."""
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
    service = PaperSignalExecutionService(
        coordinator=coordinator, paper_trading_service=trading_service, quantity=Decimal("10")
    )
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

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
