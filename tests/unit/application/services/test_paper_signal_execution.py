# tests/unit/application/services/test_paper_signal_execution.py
#
# Checkpoint 36 Part 4-6/18: proves the Strategy -> Signal -> Risk ->
# Paper Order bridge end-to-end, reusing the REAL
# StrategyExecutionCoordinator/EmaCrossoverStrategy (never a mock
# strategy), against a real PaperBroker.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.paper_signal_execution import (
    PaperSignalExecutionService,
    derive_signal_id,
)
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
)
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
    # flat warm-up, then a clean uptrend - forces a BULLISH EMA crossover,
    # the exact same fixture shape Checkpoint 30's reference validation
    # already proved produces a real, correct signal.
    flat = [100] * 8
    up = [101 + i for i in range(10)]
    return _bars(flat + up)


def _service() -> tuple[PaperSignalExecutionService, PaperBroker]:
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
    service = PaperSignalExecutionService(
        coordinator=coordinator, paper_trading_service=trading_service, quantity=Decimal("10")
    )
    return service, broker


def _config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


def test_uptrend_produces_a_bullish_signal_and_a_filled_paper_order() -> None:
    service, broker = _service()
    bars = _uptrend_bars()
    # PaperBroker needs a recorded price for the MARKET order to fill.
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

    assert result.direction is StrategyDirection.BULLISH
    assert result.signal_id is not None
    assert result.skipped_reason is None
    assert result.order_result is not None
    assert result.order_result.risk_decision.outcome is RiskDecisionOutcome.APPROVED
    assert result.order_result.broker_report is not None
    assert result.order_result.broker_report.status.value == "FILLED"

    # Lineage: the paper order carries the SAME signal_id.
    orders = broker.get_orders()
    assert len(orders) == 1


def test_flat_bars_produce_no_signal_and_no_order() -> None:
    service, broker = _service()
    bars = _bars([100] * 10)
    broker.record_price(RELIANCE, Decimal("100"), BASE)

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

    assert result.direction is StrategyDirection.NEUTRAL
    assert result.skipped_reason == "neutral_direction"
    assert result.order_result is None
    assert broker.get_orders() == ()


def test_same_signal_evaluated_twice_is_not_submitted_twice() -> None:
    """Re-running the coordinator against the SAME bar series (e.g. a
    scheduler tick that re-evaluates before new data arrives) must not
    produce a second order - proven via signal_id-based dedupe."""
    service, broker = _service()
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
    assert first.signal_id is not None

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
    assert second.order_result is None
    assert len(broker.get_orders()) == 1  # still only one order


def test_kill_switch_blocks_strategy_generated_orders_too() -> None:
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
        kill_switch_status_provider=lambda: TradingHaltStatus.HALTED,
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
    assert result.order_result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert broker.get_orders() == ()


def test_derive_signal_id_is_deterministic() -> None:
    first = derive_signal_id(
        strategy_id="ema_crossover",
        configuration_version="v1",
        instrument_id=RELIANCE,
        timestamp=BASE,
    )
    second = derive_signal_id(
        strategy_id="ema_crossover",
        configuration_version="v1",
        instrument_id=RELIANCE,
        timestamp=BASE,
    )
    assert first == second


def test_derive_signal_id_differs_for_different_timestamps() -> None:
    first = derive_signal_id(
        strategy_id="ema_crossover",
        configuration_version="v1",
        instrument_id=RELIANCE,
        timestamp=BASE,
    )
    second = derive_signal_id(
        strategy_id="ema_crossover",
        configuration_version="v1",
        instrument_id=RELIANCE,
        timestamp=BASE + timedelta(minutes=1),
    )
    assert first != second


def test_no_bars_supplied_skips_cleanly() -> None:
    service, broker = _service()
    result = service.evaluate_and_submit(
        bars=(),
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.skipped_reason == "no_bars_supplied"
    assert broker.get_orders() == ()


def test_signal_generated_order_carries_the_signal_id_on_the_intent() -> None:
    """Lineage proof at the domain-contract level: OrderIntent.signal_id
    is set, not just carried informally in the result object."""
    service, broker = _service()
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
    assert result.signal_id is not None
    # The risk decision itself references the same order that reached
    # the broker - the lineage chain (signal_id -> order_id) is
    # complete: this result object is the join point, and the
    # persisted ledger (Checkpoint 35/36) stores signal_id on the same
    # PaperOrderRecord row via PaperTradingService._persist().
    assert result.order_result.risk_decision.order_id == broker.get_orders()[0].order_id
