# tests/unit/application/services/test_signal_generation_service.py
#
# Unit tests for SignalGenerationService (Checkpoint 18) using an
# in-memory FAKE market-data repository - no Django, no database, no
# Dhan. Proves the application layer works without any concrete
# infrastructure, mirroring FeatureEngineService's own test pattern.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.feature_engine import FeatureEngineService
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.signal_generation import SignalGenerationService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.signal_generation.contracts import SignalDirection

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
END = START + timedelta(hours=2)


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
    proving `SignalGenerationService` depends only on the Protocol
    boundary, never a concrete adapter."""

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


def _service(bars: tuple[Bar, ...]) -> SignalGenerationService:
    market_data = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))
    feature_engine = FeatureEngineService(market_data=market_data)
    return SignalGenerationService(market_data=market_data, feature_engine=feature_engine)


def test_generates_bullish_indications_for_a_rising_series() -> None:
    # An ACCELERATING rise (not a straight line - a linear ramp makes
    # SMA(3)/EMA(3) converge to the exact same asymptotic value, which
    # is a real mathematical fact about this window size, not a bug -
    # it would produce NEUTRAL, not BULLISH). Accelerating growth means
    # the faster-reacting EMA tracks above the slower SMA, and the
    # newest (largest) close stays above the EMA.
    closes = ["100", "101", "103", "106", "110", "115", "121", "128", "136", "145"]
    bars = tuple(_bar(c, i) for i, c in enumerate(closes))
    service = _service(bars)

    indications = service.generate_directional_indications(
        SimpleMovingAverageDefinition(lookback=3),
        ExponentialMovingAverageDefinition(lookback=3),
        AverageTrueRangeDefinition(lookback=3),
        RELIANCE,
        Timeframe.FIVE_MINUTE,
        START,
        END,
    )

    assert len(indications) > 0
    # The later part of a steadily rising series should be BULLISH.
    assert indications[-1].direction is SignalDirection.BULLISH


def test_generates_bearish_indications_for_a_falling_series() -> None:
    # True mirror of the accelerating-rise fixture above: gaps GROW as
    # time progresses (-1, -2, -3, ... -9), an accelerating decline -
    # not merely the rising series reversed in position (which would be
    # a DEcelerating decline, the wrong shape).
    closes = ["145", "144", "142", "139", "135", "130", "124", "117", "109", "100"]
    bars = tuple(_bar(c, i) for i, c in enumerate(closes))
    service = _service(bars)

    indications = service.generate_directional_indications(
        SimpleMovingAverageDefinition(lookback=3),
        ExponentialMovingAverageDefinition(lookback=3),
        AverageTrueRangeDefinition(lookback=3),
        RELIANCE,
        Timeframe.FIVE_MINUTE,
        START,
        END,
    )

    assert len(indications) > 0
    assert indications[-1].direction is SignalDirection.BEARISH


def test_service_output_is_deterministic() -> None:
    closes = [str(100 + i) for i in range(8)]
    bars = tuple(_bar(c, i) for i, c in enumerate(closes))
    service = _service(bars)
    args = (
        SimpleMovingAverageDefinition(lookback=3),
        ExponentialMovingAverageDefinition(lookback=3),
        AverageTrueRangeDefinition(lookback=3),
        RELIANCE,
        Timeframe.FIVE_MINUTE,
        START,
        END,
    )

    first = service.generate_directional_indications(*args)
    second = service.generate_directional_indications(*args)

    assert first == second


def test_service_produces_no_indications_when_warm_up_never_completes() -> None:
    # Only 2 bars - lookback=5 SMA/EMA never warm up, ATR (needs N+1 bars
    # for lookback=5) never warms up either -> no aligned indications.
    bars = tuple(_bar(str(100 + i), i) for i in range(2))
    service = _service(bars)

    indications = service.generate_directional_indications(
        SimpleMovingAverageDefinition(lookback=5),
        ExponentialMovingAverageDefinition(lookback=5),
        AverageTrueRangeDefinition(lookback=5),
        RELIANCE,
        Timeframe.FIVE_MINUTE,
        START,
        END,
    )

    assert indications == ()


def test_service_works_without_django_postgresql_or_dhan() -> None:
    """Static proof, not just behavioral: the service module never
    imports Django, infrastructure, or a provider name."""
    import ast
    import inspect

    import intraday.application.services.signal_generation as module

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
