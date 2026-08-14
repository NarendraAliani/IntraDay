# tests/unit/application/services/test_strategy_execution_service.py
#
# Checkpoint 26 Part 15/17: end-to-end test of
# `DiagnosticStrategyExecutionService` against an in-memory FAKE
# historical repository - proving strategies run correctly on
# fixture/historical data (the only permitted source), no Django, no
# database, no live market data anywhere in this test's dependency
# graph.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.strategy_execution import (
    DiagnosticStrategyExecutionService,
    build_coordinator,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)


class FakeHistoricalMarketDataRepository:
    """Same shape as `HistoricalMarketDataRepository` (Protocol,
    structural typing), mirroring
    test_signal_generation_service.py's own precedent."""

    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._bars = bars

    def get_bars(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        return tuple(
            bar
            for bar in self._bars
            if bar.instrument_id == instrument_id
            and bar.timeframe == timeframe
            and start <= bar.timestamp <= end
        )


def _rising_bars(count: int) -> tuple[Bar, ...]:
    bars = []
    price = Decimal("100")
    for i in range(count):
        price += 1
        bars.append(
            Bar(
                instrument_id=RELIANCE,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=START + timedelta(minutes=i),
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


def test_diagnostic_service_produces_signals_from_fixture_bars_only() -> None:
    bars = _rising_bars(20)
    fake_repo = FakeHistoricalMarketDataRepository(bars)
    market_data = HistoricalMarketDataService(repository=fake_repo)

    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = build_coordinator(registry)
    service = DiagnosticStrategyExecutionService(market_data=market_data, coordinator=coordinator)

    configs = {
        "ema_crossover": StrategyConfigurationValues(
            "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        )
    }
    result = service.run(
        RELIANCE, Timeframe.ONE_MINUTE, START, START + timedelta(minutes=19), configs
    )
    assert len(result.signals) == 1
    assert result.signals[0].strategy_id == "ema_crossover"
    assert result.failures == ()
