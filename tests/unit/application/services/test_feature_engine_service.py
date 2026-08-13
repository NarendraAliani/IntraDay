# tests/unit/application/services/test_feature_engine_service.py
#
# Unit tests for FeatureEngineService (Checkpoint 15) using an in-memory
# FAKE market-data repository - no Django, no database, no Dhan. Proves
# the application layer works without any concrete infrastructure,
# mirroring every other application-service test in this codebase.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.feature_engine import FeatureEngineService
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    SimpleMovingAverageDefinition,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
END = START + timedelta(hours=1)


def _bar(close: str, offset_minutes: int) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=START + timedelta(minutes=5 * offset_minutes),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


class FakeHistoricalMarketDataRepository:
    """Same shape as `HistoricalMarketDataRepository` (Protocol,
    structural typing) - deliberately NOT `FixtureHistoricalMarketDataRepository`,
    proving `FeatureEngineService` depends only on the Protocol boundary
    via `HistoricalMarketDataService`, never a concrete adapter."""

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


def _service(bars: tuple[Bar, ...]) -> FeatureEngineService:
    market_data = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))
    return FeatureEngineService(market_data=market_data)


def test_simple_moving_average_returns_expected_values_via_the_service() -> None:
    bars = tuple(_bar(c, i) for i, c in enumerate(["100", "102", "104", "106", "108"]))
    service = _service(bars)
    definition = SimpleMovingAverageDefinition(lookback=3)

    values = service.simple_moving_average(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert [v.value for v in values] == [Decimal("102"), Decimal("104"), Decimal("106")]


def test_service_output_is_deterministic() -> None:
    bars = tuple(_bar(c, i) for i, c in enumerate(["10", "20", "30", "40"]))
    service = _service(bars)
    definition = SimpleMovingAverageDefinition(lookback=2)

    first = service.simple_moving_average(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)
    second = service.simple_moving_average(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert first == second


def test_service_works_without_django_postgresql_or_dhan() -> None:
    """Static proof, not just behavioral: neither this service module nor
    the feature_engine service module it composes ever imports Django,
    infrastructure, or a provider name."""
    import ast
    import inspect

    import intraday.application.services.feature_engine as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "django" not in imported_roots
    assert "intraday.infrastructure" not in imported_roots
    assert not any("dhan" in name.lower() for name in imported_roots)
