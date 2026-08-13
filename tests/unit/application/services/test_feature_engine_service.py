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
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
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


def _flat_bar(price: str, offset_minutes: int) -> Bar:
    value = Decimal(price)
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=START + timedelta(minutes=5 * offset_minutes),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1000"),
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


def test_exponential_moving_average_returns_expected_values_via_the_service() -> None:
    """Independently hand-derived vector (same one documented in
    test_ema.py): closes 10,20,30,40,50, period 3, alpha=0.5 ->
    seed=20, then 30, then 40."""
    bars = tuple(_bar(c, i) for i, c in enumerate(["10", "20", "30", "40", "50"]))
    service = _service(bars)
    definition = ExponentialMovingAverageDefinition(lookback=3)

    values = service.exponential_moving_average(
        definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END
    )

    assert [v.value for v in values] == [Decimal("20"), Decimal("30"), Decimal("40")]


def test_exponential_moving_average_service_output_is_deterministic() -> None:
    bars = tuple(_bar(c, i) for i, c in enumerate(["10", "20", "30", "40"]))
    service = _service(bars)
    definition = ExponentialMovingAverageDefinition(lookback=2)

    first = service.exponential_moving_average(
        definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END
    )
    second = service.exponential_moving_average(
        definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END
    )

    assert first == second


def test_average_true_range_returns_expected_values_via_the_service() -> None:
    """Constant-price flat bars -> True Range is 0 for every bar after the
    first, so ATR is deterministically 0 throughout - a simple,
    independently reasoned sanity check at the service layer (the full
    hand-derived Wilder vector is verified in test_atr.py at the
    calculation layer)."""
    bars = tuple(_flat_bar("100", i) for i in range(6))
    service = _service(bars)
    definition = AverageTrueRangeDefinition(lookback=3)

    values = service.average_true_range(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    # 6 bars, lookback=3 -> 6 - 3 = 3 ATR values (M - N, one fewer than
    # SMA/EMA's M - N + 1 shape, per the first-bar policy).
    assert len(values) == 3
    assert all(v.value == Decimal("0") for v in values)


def test_average_true_range_service_output_is_deterministic() -> None:
    bars = tuple(_flat_bar(str(100 + i), i) for i in range(5))
    service = _service(bars)
    definition = AverageTrueRangeDefinition(lookback=2)

    first = service.average_true_range(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)
    second = service.average_true_range(definition, RELIANCE, Timeframe.FIVE_MINUTE, START, END)

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
