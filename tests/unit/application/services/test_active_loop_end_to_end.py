# tests/unit/application/services/test_active_loop_end_to_end.py
#
# Checkpoint 38 Part 18: the PAPER-mode end-to-end acceptance scenario.
# Chains every real, already-tested component this project has built
# through Checkpoint 38 into ONE continuous scenario - never a mock of
# any internal component (only the Telegram/Discord network boundary is
# faked, clearly labelled `FakeProvider`, per Part 22's explicit
# "fake-provider tests must remain clearly labelled").
#
# Chain proven: canonical bars -> StrategyExecutionCoordinator ->
# StrategySignal -> derived signal_id -> VALIDATED_SIGNAL communication
# -> risk evaluation -> PaperBroker order -> ledger sync ->
# reconciliation -> SignalPipelineReport/CommunicationDeliveryReport.
#
# Failure scenarios (Part 18 B-L) are each a dedicated test function
# below, not folded into the happy path, so each produces its own
# deterministic, independently-readable result.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.signal_communication import (
    NotificationRouter,
    SignalCommunicationService,
)
from intraday.application.services.strategy_execution import build_coordinator
from intraday.communication.contracts.signal_communication import CommunicationChannel
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.communication_ledger_repository import (
    DjangoCommunicationLedgerRepository,
)
from intraday.infrastructure.persistence.models import CommunicationLedgerRecord, PaperOrderRecord
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


class FakeProvider:
    """FAKE, in-memory only - never a real Telegram/Discord network
    call. Clearly labelled per Part 22's explicit requirement."""

    channel = CommunicationChannel.TELEGRAM
    provider_name = "telegram-fake"
    destination_masked = "****fake"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        return True, "fake-msg-1", None, None, False


def _build_active_loop(
    *, kill_switch: TradingHaltStatus = TradingHaltStatus.ACTIVE
) -> tuple[PaperSignalExecutionService, PaperBroker, DjangoPaperLedgerRepository, FakeProvider]:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)

    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    ledger = DjangoPaperLedgerRepository()
    trading_service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: kill_switch,
        clock=lambda: BASE,
        ledger=ledger,
    )

    fake_provider = FakeProvider()
    communication = SignalCommunicationService(
        router=NotificationRouter(
            providers=(fake_provider,), ledger=DjangoCommunicationLedgerRepository()
        )
    )

    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
    )
    return service, broker, ledger, fake_provider


def test_full_paper_active_loop_end_to_end() -> None:
    """Steps 1-21 of Part 18's happy path, everything this project can
    honestly assemble today: bars -> signal -> communication -> risk ->
    paper order -> fill -> ledger sync -> reconciliation clean."""
    service, broker, ledger, fake_provider = _build_active_loop()
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

    # 5-6: signal generated and validated.
    assert result.signal_id is not None
    # 7-8: communication event created and delivered to the fake provider.
    assert len(fake_provider.sent) == 2  # VALIDATED_SIGNAL, then ORDER_FILLED
    assert "VALIDATED SIGNAL" in fake_provider.sent[0]
    # 9-11: risk evaluated, paper order created and filled.
    assert result.order_result is not None
    assert result.order_result.broker_report is not None
    assert result.order_result.broker_report.status.value == "FILLED"
    # 12: position created.
    assert len(broker.get_positions()) == 1
    # 19: reports updated - real persisted rows exist.
    assert PaperOrderRecord.objects.filter(signal_id=str(result.signal_id)).exists()
    assert CommunicationLedgerRecord.objects.filter(signal_id=str(result.signal_id)).exists()
    # 20: reconciliation passes - ledger and broker agree.
    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)
    assert report.is_clean


# --------------------------------------------------------------------
# Failure scenarios (Part 18 B-L) - each deterministic and auditable.
# --------------------------------------------------------------------


def test_scenario_c_duplicate_signal_produces_no_second_order_or_message() -> None:
    service, broker, _, fake_provider = _build_active_loop()
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

    first = service.evaluate_and_submit(
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
    sent_after_first = len(fake_provider.sent)

    second = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset({str(first.signal_id)}),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert second.skipped_reason == "signal_already_processed"
    assert len(broker.get_orders()) == 1  # still only one order
    assert len(fake_provider.sent) == sent_after_first  # no additional message sent


def test_scenario_e_communication_provider_failure_does_not_block_the_order() -> None:
    """A communication FAILURE must never prevent the order from being
    evaluated/submitted - the two paths (Part 7) are independent."""

    class AlwaysFailingProvider:
        channel = CommunicationChannel.TELEGRAM
        provider_name = "telegram-failing"
        destination_masked = "****fail"

        def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
            return False, None, "PROVIDER_ERROR", "simulated permanent failure", False

    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)
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
    communication = SignalCommunicationService(
        router=NotificationRouter(providers=(AlwaysFailingProvider(),), ledger=None)
    )
    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
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

    # Communication failed, but the order still went through.
    assert result.order_result is not None
    assert result.order_result.broker_report is not None
    assert result.order_result.broker_report.status.value == "FILLED"


def test_scenario_f_kill_switch_blocks_order_but_signal_and_communication_survive() -> None:
    service, broker, _, fake_provider = _build_active_loop(kill_switch=TradingHaltStatus.HALTED)
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

    assert result.signal_id is not None  # the signal itself is untouched
    assert broker.get_orders() == ()  # no order reached the broker
    assert len(fake_provider.sent) == 2  # VALIDATED_SIGNAL + EXECUTION_BLOCKED
    assert "EXECUTION BLOCKED" in fake_provider.sent[1]


def test_scenario_a_stale_market_data_blocks_execution_but_not_communication() -> None:
    service, broker, _, fake_provider = _build_active_loop()
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

    result = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=True,  # <-- stale
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )

    assert result.order_result is not None
    assert result.order_result.risk_decision.outcome.value == "REJECTED"
    assert broker.get_orders() == ()
    assert len(fake_provider.sent) == 2
    assert "EXECUTION BLOCKED" in fake_provider.sent[1]


def test_scenario_i_reconciliation_mismatch_is_detected_after_a_direct_ledger_edit() -> None:
    service, broker, ledger, _ = _build_active_loop()
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
    order_id = str(result.order_result.broker_report.order_id)
    PaperOrderRecord.objects.filter(order_id=order_id).update(status="PENDING")

    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)

    assert not report.is_clean
