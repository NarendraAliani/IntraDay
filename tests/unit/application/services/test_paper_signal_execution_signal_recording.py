# tests/unit/application/services/test_paper_signal_execution_signal_recording.py
#
# Checkpoint 62.x: proves the new, optional `signal_recorder` hook -
# a REAL signal is persisted exactly once when one is genuinely
# produced, and NO record is created for a flat/neutral evaluation
# that produces no signal. This is the direct proof for the user's
# own explicit rule this checkpoint: "prove that a normal market-data
# update does NOT create a signal unless the strategy engine actually
# returns a signal."
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, SignalId, Timeframe
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
class _RecordedCall:
    signal_id: SignalId
    strategy_id: str
    instrument_id: InstrumentId
    direction: str
    risk_status: str
    order_status: str


class _FakeSignalRecorder:
    """A pure in-memory stand-in for `DjangoSignalRepository` -
    satisfies `SignalRecorder` structurally without touching a real
    database, matching this project's own established Protocol-
    fake-in-application-tests pattern (e.g. `_FakeExitPlanAttacher`
    precedent elsewhere in this test suite)."""

    def __init__(self) -> None:
        self.calls: list[_RecordedCall] = []

    def record_signal(
        self,
        *,
        signal_id: SignalId,
        strategy_id: str,
        instrument_id: InstrumentId,
        direction: str,
        price: Decimal,
        timeframe: str,
        signal_timestamp: datetime,
        risk_status: str,
        risk_reason: str,
        order_status: str,
    ) -> None:
        self.calls.append(
            _RecordedCall(
                signal_id=signal_id,
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                direction=direction,
                risk_status=risk_status,
                order_status=order_status,
            )
        )


def _service(recorder: _FakeSignalRecorder) -> tuple[PaperSignalExecutionService, PaperBroker]:
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
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        signal_recorder=recorder,
    )
    return service, broker


def test_a_real_signal_is_recorded_exactly_once() -> None:
    recorder = _FakeSignalRecorder()
    service, broker = _service(recorder)
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

    assert result.signal_id is not None
    assert len(recorder.calls) == 1
    recorded = recorder.calls[0]
    assert recorded.signal_id == result.signal_id
    assert recorded.strategy_id == "ema_crossover"
    assert recorded.direction == "BULLISH"
    assert recorded.risk_status == "APPROVED"
    assert recorded.order_status == "FILLED"


def test_a_flat_bar_series_with_no_signal_records_nothing() -> None:
    """THE proof: a normal market-data update that produces no
    qualifying strategy signal must NEVER create a signal record - a
    signal-monitor UI querying this table can never show a fabricated
    row for a bar the strategy found nothing actionable in."""
    recorder = _FakeSignalRecorder()
    service, broker = _service(recorder)
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

    assert result.signal_id is None
    assert recorder.calls == []


def test_an_already_processed_signal_is_not_recorded_again() -> None:
    """A signal the caller already marked as processed (restart-safety
    dedup, Checkpoint 39) must not be re-recorded - `evaluate_and_submit()`
    returns early via `skipped_reason="signal_already_processed"` before
    ever reaching the recording call."""
    recorder = _FakeSignalRecorder()
    service, broker = _service(recorder)
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
    assert len(recorder.calls) == 1

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
    assert len(recorder.calls) == 1  # still exactly one - no duplicate


def test_no_recorder_supplied_means_no_recording_attempted() -> None:
    """`signal_recorder=None` (the default, matching every pre-existing
    caller/test of this service) must not raise or behave differently
    - this checkpoint's addition is purely additive."""
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

    assert result.signal_id is not None  # unaffected by the missing recorder
