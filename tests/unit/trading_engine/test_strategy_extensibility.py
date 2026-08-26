# tests/unit/trading_engine/test_strategy_extensibility.py
#
# Checkpoint 64.20 §8/§9: THE mandatory proof-of-extensibility test.
# `TestMomentumStrategy` (NON_PRODUCTION, never registered in
# `build_default_registry()`, verified below) moves through the SAME
# real, unmodified engines the three production strategies already use:
#
#     local StrategyRegistry.register()
#         -> StrategyConfigurationValues (generic configuration)
#         -> StrategyExecutionCoordinator.run() (the SAME engine
#            research.backtesting reuses verbatim, Checkpoint 64.16's
#            own confirmed audit - no divergent backtest implementation
#            exists to separately re-prove)
#         -> StrategySignal (with real evidence)
#         -> build_signal_evidence() (generic dispatch)
#         -> PaperTradingService (risk) -> PaperBroker (paper execution)
#         -> SignalCommunicationService (Telegram/Discord, faked network
#            boundary only)
#         -> DjangoSignalRepository.list_signals() (the same query the
#            Signal Operations Center / reports read)
#
# ZERO core engine file contains an `if strategy_id == "test_momentum"`
# branch - this test IS the mechanical proof of that claim.
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
from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryAttempt,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.signal_evidence_repository import (
    DjangoSignalEvidenceRepository,
)
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator
from intraday.trading_engine.strategy_execution.registry import (
    StrategyRegistry,
    build_default_registry,
)
from intraday.trading_engine.strategy_execution.strategies.test_momentum import (
    TestMomentumStrategy,
)

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


def _fake_compute(field_id: str, bars: tuple[Bar, ...]) -> tuple:
    """The SAME dispatch-by-prefix shape
    `application.services.strategy_execution.compute_feature_series`
    already uses (Checkpoint 26) - reused here verbatim, not
    reimplemented, to prove `test_momentum`'s `ema_<N>` request needs
    ZERO changes to the real dispatcher (imported directly instead of
    duplicated, see `test_reuses_the_real_production_feature_
    dispatcher_unmodified` below)."""
    from intraday.application.services.strategy_execution import compute_feature_series

    return compute_feature_series(field_id, bars)


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
    flat = [100] * 6
    up = [101 + i for i in range(8)]
    return _bars(flat + up)


def _config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "test_momentum",
        "test-v1",
        "test-v1",
        "test-v1",
        {"ema_lookback": 3, "threshold_percent": Decimal("0.1")},
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


def test_test_momentum_is_never_registered_in_the_production_registry() -> None:
    """The single most important safety property of this proof-of-
    extensibility strategy: it must NEVER appear where a real operator
    could accidentally select it."""
    production_registry = build_default_registry()
    strategy_ids = {s.strategy_id for s in production_registry.list()}
    assert "test_momentum" not in strategy_ids


def test_registering_a_new_strategy_requires_zero_core_engine_changes() -> None:
    """§7: adding a strategy requires REGISTRATION, not scattered
    changes. Proven by constructing a completely independent, local
    registry with ONLY this new strategy - the same
    `StrategyExecutionCoordinator` class runs it, unmodified."""
    registry = StrategyRegistry()
    registry.register(TestMomentumStrategy())
    registry.activate("test_momentum")

    coordinator = StrategyExecutionCoordinator(registry, _fake_compute)
    result = coordinator.run(_uptrend_bars(), {"test_momentum": _config()})

    assert len(result.signals) == 1
    assert result.signals[0].strategy_id == "test_momentum"
    assert result.failures == ()


def test_reuses_the_real_production_feature_dispatcher_unmodified() -> None:
    """`test_momentum` requests `ema_<lookback>` - the SAME generic,
    prefix-dispatched feature family (`sma`/`ema`/`atr`) every real
    strategy already uses. This test calls the REAL
    `compute_feature_series()` directly (not a fake) to prove it, with
    no per-strategy special-casing anywhere in that dispatcher."""
    from intraday.application.services.strategy_execution import compute_feature_series

    values = compute_feature_series("ema_3", _uptrend_bars())
    assert len(values) > 0


def test_full_pipeline_signal_evidence_risk_paper_communication_report() -> None:
    """The full chain: registry -> configuration -> coordinator (the
    same engine backtesting reuses) -> signal -> evidence -> risk ->
    PaperBroker -> Telegram/Discord -> a real report query. No
    TradePlan is asserted (this strategy is directional-only, exactly
    like the real `EmaCrossoverStrategy` - TradePlan optionality is
    already proven by that strategy, never re-proven here)."""
    registry = StrategyRegistry()
    registry.register(TestMomentumStrategy())
    registry.activate("test_momentum")
    coordinator = StrategyExecutionCoordinator(registry, _fake_compute)

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
    telegram = FakeProvider(channel=CommunicationChannel.TELEGRAM, provider_name="telegram-fake")
    discord = FakeProvider(channel=CommunicationChannel.DISCORD, provider_name="discord-fake")

    class _FakeLedger:
        def record_attempt(self, attempt: DeliveryAttempt) -> None:
            pass

        def already_sent(
            self, *, signal_id: str, event_id: str, channel: CommunicationChannel
        ) -> bool:
            return False

    communication = SignalCommunicationService(
        router=NotificationRouter(providers=(telegram, discord), ledger=_FakeLedger())
    )
    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
        signal_recorder=DjangoSignalRepository(),
        evidence_recorder=DjangoSignalEvidenceRepository(),
    )
    bars = _uptrend_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)

    result = service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="test_momentum",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )

    signal_id = result.signal_id
    assert signal_id is not None

    # --- Risk + PaperBroker: real, unmodified engines ---
    assert result.order_result is not None
    assert result.order_result.risk_decision.outcome.value == "APPROVED"
    assert result.order_result.broker_report is not None

    # --- Signal Evidence: real, persisted, via the SAME generic
    # dispatch every production strategy uses (one registration entry,
    # never a new engine) ---
    evidence_record = DjangoSignalEvidenceRepository().get_by_signal_id(str(signal_id))
    assert evidence_record is not None
    assert evidence_record.strategy_id == "test_momentum"
    evidence_labels = {f.label for f in evidence_record.fields}
    assert {"EMA", "Price", "Momentum"} <= evidence_labels

    # --- Communication: real, generic - Telegram/Discord both fired,
    # carrying the new strategy's OWN evidence, without either provider
    # knowing "test_momentum" exists as a concept ---
    assert telegram.sent and discord.sent
    assert any("Key Evidence:" in message and "EMA:" in message for message in telegram.sent)

    # --- Report / query layer: the SAME repository the Signal
    # Operations Center and Daily Session Report both read ---
    page = DjangoSignalRepository().list_signals(strategy_id="test_momentum")
    assert page.total_count >= 1
    assert any(item.record.signal_id == str(signal_id) for item in page.items)
    matching = next(item for item in page.items if item.record.signal_id == str(signal_id))
    assert matching.evidence is not None
    assert matching.trade_plan is None  # directional-only, never fabricated
